from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pmo_skills.changes import Proposal, fingerprint, preview
from pmo_skills.cli import main
from pmo_skills.models import Project
from pmo_skills.report import render
from pmo_skills.review import assess

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    return json.loads((ROOT / "examples/project.json").read_text())


def test_real_demo_flags_reported_green(data):
    result = assess(Project.model_validate(data))
    assert result.assessed_status == "RED"
    assert {f.code for f in result.findings} == {"OPEN_BLOCKER", "HIGH_RISK", "STATUS_MISMATCH"}


@pytest.mark.parametrize(
    "case", json.loads((ROOT / "evals/cases.json").read_text()), ids=lambda c: c["id"]
)
def test_labeled_fixture(case):
    result = assess(Project.model_validate(case["project"]))
    assert result.assessed_status == case["expected_status"]
    assert sorted({f.code for f in result.findings}) == case["expected_codes"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_id",
        "fake_quote",
        "unknown_source",
        "future_source",
        "future_update",
        "risk_blocker",
        "bad_milestone",
        "closed_without_evidence",
        "boolean_score",
        "out_of_range_score",
        "extra_field",
        "blank_owner",
        "issue_score",
        "bad_date",
    ],
)
def test_invalid_contract(data, mutation):
    if mutation == "duplicate_id":
        data["items"].append(copy.deepcopy(data["items"][0]))
    elif mutation == "fake_quote":
        data["items"][0]["evidence"][0]["quote"] = "Everything is resolved."
    elif mutation == "unknown_source":
        data["items"][0]["evidence"][0]["source_id"] = "MISSING"
    elif mutation == "future_source":
        data["sources"][0]["observed_on"] = "2026-10-03"
    elif mutation == "future_update":
        data["items"][0]["updated_on"] = "2026-10-03"
    elif mutation == "risk_blocker":
        data["items"][1].update(blocker=True, milestone_id="M1")
    elif mutation == "bad_milestone":
        data["items"][0]["milestone_id"] = "MISSING"
    elif mutation == "closed_without_evidence":
        data["items"][0]["status"] = "closed"
    elif mutation == "boolean_score":
        data["items"][1]["likelihood"] = True
    elif mutation == "out_of_range_score":
        data["items"][1]["impact"] = 6
    elif mutation == "extra_field":
        data["approved"] = True
    elif mutation == "blank_owner":
        data["items"][0]["owner"] = "   "
    elif mutation == "issue_score":
        data["items"][0]["impact"] = 5
    else:
        data["as_of"] = "2026-02-30"
    with pytest.raises(ValidationError):
        Project.model_validate(data)


def proposal_data(data):
    candidate = copy.deepcopy(data)
    candidate["revision"] = 2
    candidate["sources"].append(
        {
            "id": "S2",
            "title": "Closure",
            "observed_on": "2026-10-02",
            "text": "The interface repair passed verification. Close I1.",
        }
    )
    candidate["items"][0].update(
        status="closed",
        updated_on="2026-10-02",
        closure_evidence=[
            {"source_id": "S2", "quote": "The interface repair passed verification. Close I1."}
        ],
    )
    return {
        "base_sha256": fingerprint(Project.model_validate(data)),
        "reason": "Verified repair",
        "candidate": candidate,
    }


def test_preview_is_read_only_and_detects_closure(data):
    base = Project.model_validate(data)
    before = base.model_dump_json()
    result = preview(base, Proposal.model_validate(proposal_data(data)))
    assert result.decision == "HUMAN_REVIEW_REQUIRED"
    assert any(c.path == "items/I1/status" for c in result.changes)
    assert base.model_dump_json() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_hash",
        "same_revision",
        "remove_id",
        "rewrite_source",
        "change_kind",
        "backdate",
        "unsupported_change",
        "remove_milestone",
    ],
)
def test_unsafe_proposals_rejected(data, mutation):
    proposal = proposal_data(data)
    c = proposal["candidate"]
    if mutation == "stale_hash":
        proposal["base_sha256"] = "0" * 64
    elif mutation == "same_revision":
        c["revision"] = 1
    elif mutation == "remove_id":
        c["items"].pop()
    elif mutation == "rewrite_source":
        c["sources"][0]["title"] = "Changed historical title"
    elif mutation == "change_kind":
        c["items"][1].update(kind="assumption", likelihood=None, impact=None)
    elif mutation == "backdate":
        c["items"][1]["updated_on"] = "2026-09-01"
    elif mutation == "unsupported_change":
        c["items"][1]["owner"] = "Invented owner"
    else:
        c["milestones"] = []
        c["items"][0].update(blocker=False, milestone_id=None)
    with pytest.raises(ValueError):
        preview(Project.model_validate(data), Proposal.model_validate(proposal))


def test_report_neutralizes_active_markup(data):
    data["name"] = "[click](https://example.invalid) <script> |"
    report = render(Project.model_validate(data))
    assert "<script>" not in report
    assert "\\[click\\]" in report
    assert "Policy screening: **RED**" in report
    assert "S1" in report


def test_cli_validation_errors_do_not_echo_source_text(data, tmp_path, capsys):
    data["sources"][0]["observed_on"] = "secret-invalid-value"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    assert main(["validate", str(path)]) == 2
    error = capsys.readouterr().err
    assert "secret-invalid-value" not in error
    assert "invalid_contract" in error


def test_trace_has_no_evidence_text(data, tmp_path, capsys):
    path, trace = tmp_path / "project.json", tmp_path / "trace.jsonl"
    path.write_text(json.dumps(data))
    assert main(["--trace", str(trace), "review", str(path)]) == 0
    spans = [json.loads(line) for line in trace.read_text().splitlines()]
    assert {s["name"] for s in spans} >= {"pmo.assess", "pmo.validate", "pmo.command"}
    assert "The interface is unavailable" not in trace.read_text()
    assert main(["--trace", str(trace), "review", str(path)]) == 2
    capsys.readouterr()


def test_cli_missing_file(tmp_path, capsys):
    assert main(["review", str(tmp_path / "absent.json")]) == 2
    assert "FileNotFoundError" in capsys.readouterr().err
