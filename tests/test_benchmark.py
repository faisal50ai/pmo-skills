from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import openai
import pytest

from pmo_skills.bench_contracts import Answer, Config, Outcome, ProbeOutput
from pmo_skills.bench_scoring import review_packet, score
from pmo_skills.benchmark import call_openai, execute, load_study, main, prepare, read_json
from pmo_skills.models import Evidence

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return Config(
        model="synthetic-test-model",
        repeats=1,
        max_cost_usd=10,
        input_per_million=1,
        output_per_million=1,
        pricing_reference="Synthetic unit-test prices; not real provider pricing",
    )


@pytest.fixture
def study(tmp_path, config):
    path = tmp_path / "study"
    prepare(ROOT, path, config)
    return path


def make_runs(study, fault=None):
    _, requests, cases = load_study(study)
    labels = read_json(study / "labels.json")
    case_map = {c.id: c for c in cases}
    rows = []
    for request in requests:
        case = case_map[request.case_id]
        answers = [
            Answer(
                id=k,
                value=v,
                evidence=[Evidence(source_id="S1", quote=case.sources["S1"])]
                if v is not None
                else [],
            )
            for k, v in labels[case.id].items()
        ]
        row = Outcome(
            id=request.id,
            status="completed",
            actual_model="synthetic-test-model",
            response_id="synthetic",
            output=ProbeOutput(answers=answers),
            input_tokens=100,
            output_tokens=50,
            latency_ms=20,
            estimated_cost_usd=0.00015,
        )
        if fault:
            fault(request, row)
        rows.append(row)
    (study / "runs.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in rows))
    return requests, rows


def test_preparation_pairs_and_label_isolation(study, tmp_path, config):
    manifest, requests, cases = load_study(study)
    prepare(ROOT, tmp_path / "second", config)
    assert (study / "requests.json").read_bytes() == (
        tmp_path / "second/requests.json"
    ).read_bytes()
    assert manifest.planned_requests == 20
    assert {r.condition for r in requests} == {"baseline", "skill"}
    assert [r.condition for r in requests[::2]].count("baseline") not in (0, 10)
    for i in range(0, len(requests), 2):
        a, b = requests[i : i + 2]
        assert a.case_id == b.case_id and a.input == b.input
        assert a.condition != b.condition
        payload = json.loads(a.input)
        assert set(payload) == {"sources", "questions"}
        assert "labels" not in payload
    assert len(cases) == 10
    assert not (study / "runs.jsonl").exists()


@pytest.mark.parametrize("mutation", [dict(max_requests=2), dict(max_cost_usd=0.00001)])
def test_preparation_rejects_excessive_plan(tmp_path, config, mutation):
    with pytest.raises(ValueError):
        prepare(ROOT, tmp_path / "study", config.model_copy(update=mutation))
    assert not (tmp_path / "study").exists()


@pytest.mark.parametrize(
    "file", ["cases.json", "labels.json", "requests.json", "skills.json", "schema.json"]
)
def test_frozen_inputs_reject_changes(study, file):
    with (study / file).open("a") as f:
        f.write(" ")
    with pytest.raises(ValueError, match="changed"):
        load_study(study)


def test_refusals_are_failures_not_dropped(study):
    def refusal(request, row):
        if request.condition == "baseline":
            row.status = "refused"
            row.output = None

    make_runs(study, refusal)
    result = score(study)
    assert result["baseline"]["field_accuracy"] == 0
    assert result["baseline"]["planned_runs"] == 10
    assert result["skill"]["field_accuracy"] == 1
    assert result["paired_case_mean_accuracy_delta"] == 1
    assert result["case_cluster_bootstrap_95pct_interval"] == [1, 1]
    assert result["skill"]["unsupported_claim_rate_among_reviewed"] is None


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "unknown"])
def test_score_rejects_corrupt_runs(study, mutation):
    _, rows = make_runs(study)
    if mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "missing":
        rows.pop()
    else:
        rows[0].id = "unknown"
    (study / "runs.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in rows))
    with pytest.raises(ValueError):
        score(study)


def test_duplicate_answers_and_fabricated_quotes_fail(study):
    def corrupt(request, row):
        if request.condition == "baseline":
            row.output.answers.append(copy.deepcopy(row.output.answers[0]))
        else:
            row.output.answers[0].evidence = [Evidence(source_id="S1", quote="Invented evidence.")]

    make_runs(study, corrupt)
    result = score(study)
    assert result["baseline"]["valid_answer_set_rate"] == 0
    assert result["skill"]["literal_evidence_pass_rate"] == 0


def test_blinded_semantic_review_does_not_equal_literal_match(study):
    make_runs(study)
    packet = review_packet(study)
    assert "condition" not in json.dumps(packet["reviews"])
    annotations = []
    for row in packet["reviews"]:
        annotations.append(
            dict(
                review_id=row["review_id"],
                reviewer="Synthetic test reviewer",
                judgments=[
                    dict(id=j["id"], support="unsupported", reason="Synthetic negative test label")
                    for j in row["judgments"]
                ],
            )
        )
    file = study / "annotations.json"
    file.write_text(json.dumps(annotations))
    result = score(study, file)
    assert result["skill"]["literal_evidence_pass_rate"] == 1
    assert result["skill"]["unsupported_claim_rate_among_reviewed"] == 1
    assert result["skill"]["semantic_review_coverage"] == 1
    annotations[0]["judgments"].pop()
    file.write_text(json.dumps(annotations))
    with pytest.raises(ValueError):
        score(study, file)


def test_api_error_stops_without_retry_and_keeps_denominators(study):
    calls = []

    async def fail(request, config):
        calls.append(request.id)
        return Outcome(id=request.id, status="api_error", error_type="RateLimitError", latency_ms=1)

    rows = asyncio.run(execute(study, fail))
    assert len(calls) == 1 and len(rows) == 20
    assert [r.status for r in rows].count("skipped") == 19
    result = score(study)
    assert result["paired_comparison_usable"] is False
    assert result["paired_case_mean_accuracy_delta"] is None
    with pytest.raises(FileExistsError):
        asyncio.run(execute(study, fail))


def test_unexpected_cost_stops_next_request(study):
    async def expensive(request, config):
        return Outcome(
            id=request.id,
            status="incomplete",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=config.max_cost_usd + 1,
            actual_model=config.model,
        )

    rows = asyncio.run(execute(study, expensive))
    assert len(rows) == 20 and all(r.status == "skipped" for r in rows[1:])


def test_missing_key_does_not_create_output(study, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["benchmark", "run", str(study)])
    assert main() == 2
    assert not (study / "runs.jsonl").exists()
    assert not (study / "trace.jsonl").exists()
    assert "API configuration" in capsys.readouterr().err


@pytest.mark.parametrize(
    "kind", ["completed", "refused", "incomplete", "invalid_output", "rate_limit"]
)
def test_real_sdk_with_mock_transport(study, monkeypatch, kind):
    manifest, requests, _ = load_study(study)
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if kind == "rate_limit":
            return httpx.Response(
                429,
                json={"error": {"message": "secret provider message", "type": "rate_limit_error"}},
            )
        text = "not-json" if kind == "invalid_output" else '{"answers":[]}'
        content = (
            [dict(type="refusal", refusal="Not answered")]
            if kind == "refused"
            else [dict(type="output_text", text=text, annotations=[])]
        )
        return httpx.Response(
            200,
            json=dict(
                id="resp_mock",
                object="response",
                created_at=1,
                model=manifest.config.model,
                status="incomplete" if kind == "incomplete" else "completed",
                output=[
                    dict(
                        id="msg_mock",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=content,
                    )
                ],
                usage=dict(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    input_tokens_details=dict(cached_tokens=5),
                    output_tokens_details=dict(reasoning_tokens=0),
                ),
            ),
        )

    original = openai.AsyncOpenAI

    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        return original(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    result = asyncio.run(call_openai(requests[0], manifest.config))
    assert result.status == ("api_error" if kind == "rate_limit" else kind)
    assert len(sent) == 1
    assert sent[0]["store"] is False
    assert sent[0]["text"]["format"]["strict"] is True
    assert sent[0]["max_output_tokens"] == manifest.config.max_output_tokens
    if kind == "rate_limit":
        assert "secret provider message" not in result.model_dump_json()
    else:
        assert result.input_tokens == 100 and result.cached_input_tokens == 5
        assert result.estimated_cost_usd == 0.00012
