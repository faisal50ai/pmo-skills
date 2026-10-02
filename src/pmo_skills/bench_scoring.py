"""Exact-label checks and blinded semantic review, kept deliberately separate."""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .bench_contracts import Annotation, Case, Outcome, Request
from .benchmark import load_study, read_json


def normalize(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) if value is not None else None


def load_runs(path: Path) -> tuple[list[Request], dict[str, Case], dict[str, Outcome]]:
    _, requests, cases = load_study(path)
    raw = (path / "runs.jsonl").read_text(encoding="utf-8")
    if len(raw.encode()) > 20_000_000:
        raise ValueError("Run file exceeds 20 MB")
    rows = [Outcome.model_validate_json(line) for line in raw.splitlines() if line.strip()]
    outcomes = {r.id: r for r in rows}
    if len(outcomes) != len(rows) or set(outcomes) != {r.id for r in requests}:
        raise ValueError("Missing, duplicate or unexpected runs; study is not complete")
    return requests, {c.id: c for c in cases}, outcomes


def valid_answers(case: Case, row: Outcome) -> bool:
    if row.status != "completed" or row.output is None:
        return False
    ids = [a.id for a in row.output.answers]
    return len(set(ids)) == len(ids) and set(ids) == {q.id for q in case.questions}


def literal_support(case: Case, row: Outcome) -> bool:
    if not valid_answers(case, row) or row.output is None:
        return False
    for answer in row.output.answers:
        if answer.value is not None and not answer.evidence:
            return False
        for ref in answer.evidence:
            if ref.source_id not in case.sources or ref.quote not in case.sources[ref.source_id]:
                return False
    return True


def review_packet(path: Path) -> dict[str, Any]:
    requests, cases, outcomes = load_runs(path)
    packet = []
    for request in requests:
        case, row = cases[request.case_id], outcomes[request.id]
        if not valid_answers(case, row) or row.output is None:
            continue
        packet.append(
            {
                "review_id": row.id,
                "sources": case.sources,
                "questions": [q.model_dump() for q in case.questions],
                "answers": row.output.model_dump()["answers"],
                "reviewer": "",
                "judgments": [
                    {"id": a.id, "support": None, "reason": ""} for a in row.output.answers
                ],
            }
        )
    # Opaque IDs, randomized display order, no condition/model/repeat/ground-truth labels.
    random.Random(8923).shuffle(packet)
    return {
        "instruction": "Judge whether source meaning supports each answer, including nulls. "
        "Use supported, unsupported or unclear; explain each judgment. Return only review_id, "
        "reviewer and judgments as a JSON array. Keep condition mapping hidden from reviewers.",
        "reviews": packet,
    }


def score(path: Path, annotation_path: Path | None = None) -> dict[str, Any]:
    manifest, _, _ = load_study(path)
    requests, cases, outcomes = load_runs(path)
    labels = read_json(path / "labels.json")
    annotations: dict[str, Annotation] = {}
    if annotation_path is not None:
        parsed = [Annotation.model_validate(x) for x in read_json(annotation_path)]
        annotations = {a.review_id: a for a in parsed}
        if len(annotations) != len(parsed) or not set(annotations) <= set(outcomes):
            raise ValueError("Duplicate or unknown annotation IDs")
        for request in requests:
            annotation = annotations.get(request.id)
            if annotation:
                if not valid_answers(cases[request.case_id], outcomes[request.id]):
                    raise ValueError("Cannot annotate an invalid answer set")
                ids = [j.id for j in annotation.judgments]
                if len(set(ids)) != len(ids) or set(ids) != set(labels[request.case_id]):
                    raise ValueError("Annotations must cover every answer exactly once")
    pairs: dict[tuple[str, int], dict[str, float]] = {}
    metrics: dict[str, Any] = {}
    actual_models = {o.actual_model for o in outcomes.values() if o.actual_model}
    interrupted = any(o.status in ("skipped", "api_error") for o in outcomes.values())
    comparable = (
        not interrupted
        and len(actual_models) == 1
        and all(o.actual_model is not None for o in outcomes.values())
    )
    case_rows: list[dict[str, Any]] = []
    for condition in ("baseline", "skill"):
        group = [r for r in requests if r.condition == condition]
        statuses = Counter(outcomes[r.id].status for r in group)
        correct = total = schemas = literal = strict = reviewed = unsupported = unclear = 0
        claims = reviewed_claims = false_positive = positive = detected = 0
        timings: list[float] = []
        costs: list[float] = []
        for request in group:
            case, row = cases[request.case_id], outcomes[request.id]
            expected = labels[case.id]
            valid = valid_answers(case, row)
            actual = {a.id: a for a in row.output.answers} if valid and row.output else {}
            passed = sum(
                k in actual and normalize(actual[k].value) == normalize(v)
                for k, v in expected.items()
            )
            exact = passed == len(expected)
            cited = literal_support(case, row)
            total += len(expected)
            correct += passed
            schemas += valid
            literal += cited
            strict += exact and cited
            if "contradiction" in expected:
                is_positive = expected["contradiction"] == "true"
                predicted = (
                    normalize(actual["contradiction"].value) == "true"
                    if "contradiction" in actual
                    else False
                )
                positive += is_positive
                detected += predicted and is_positive
                false_positive += predicted and not is_positive
            pairs.setdefault((case.id, request.repeat), {})[condition] = passed / len(expected)
            annotation = annotations.get(row.id)
            judgments = {j.id: j for j in annotation.judgments} if annotation else {}
            reviewed += bool(annotation)
            for answer in actual.values():
                if answer.value is not None:
                    claims += 1
                    if answer.id in judgments:
                        reviewed_claims += 1
                        unsupported += judgments[answer.id].support == "unsupported"
                        unclear += judgments[answer.id].support == "unclear"
            if row.latency_ms is not None:
                timings.append(row.latency_ms)
            if row.estimated_cost_usd is not None:
                costs.append(row.estimated_cost_usd)
            case_rows.append(
                {
                    "case_id": case.id,
                    "skill": case.skill,
                    "condition": condition,
                    "repeat": request.repeat,
                    "status": row.status,
                    "correct_fields": passed,
                    "total_fields": len(expected),
                    "literal_quotes_valid": cited,
                }
            )
        timings.sort()
        metrics[condition] = {
            "planned_runs": len(group),
            "outcomes": dict(statuses),
            "field_accuracy": correct / total,
            "correct_fields": correct,
            "total_fields": total,
            "valid_answer_set_rate": schemas / len(group),
            "literal_evidence_pass_rate": literal / len(group),
            "exact_fields_and_literal_evidence_rate": strict / len(group),
            "contradiction_recall": detected / positive if positive else None,
            "contradiction_positives": positive,
            "contradiction_false_positives": false_positive,
            "reviewed_runs": reviewed,
            "nonnull_claims": claims,
            "reviewed_nonnull_claims": reviewed_claims,
            "semantic_review_coverage": reviewed_claims / claims if claims else None,
            "unsupported_claim_rate_among_reviewed": unsupported / reviewed_claims
            if reviewed_claims
            else None,
            "unclear_claim_rate_among_reviewed": unclear / reviewed_claims
            if reviewed_claims
            else None,
            "latency_observations": len(timings),
            "p50_latency_ms": statistics.median(timings) if timings else None,
            "p95_latency_ms": timings[math.ceil(0.95 * len(timings)) - 1] if timings else None,
            "cost_observations": len(costs),
            "estimated_known_cost_usd": sum(costs),
            "cost_complete": len(costs) == len(group),
            "input_tokens_known": sum(outcomes[r.id].input_tokens or 0 for r in group),
            "output_tokens_known": sum(outcomes[r.id].output_tokens or 0 for r in group),
        }
    if any(set(pair) != {"baseline", "skill"} for pair in pairs.values()):
        raise ValueError("Unpaired study")
    by_case = {
        case: statistics.mean(
            p["skill"] - p["baseline"] for (c, _), p in pairs.items() if c == case
        )
        for case in cases
    }
    deltas = list(by_case.values())
    interval: list[float] | None = None
    if comparable and len(deltas) >= 5:
        rng = random.Random(20261002)
        boot = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
        interval = [boot[49], boot[1949]]
    return {
        "protocol": manifest.protocol,
        "requested_model": manifest.config.model,
        "actual_models": sorted(actual_models),
        "paired_comparison_usable": comparable,
        "scope": "Public synthetic component probe; not a held-out or end-to-end agent benchmark",
        "semantic_support_automatically_verified": False,
        "baseline": metrics["baseline"],
        "skill": metrics["skill"],
        "paired_case_mean_accuracy_delta": statistics.mean(deltas) if comparable else None,
        "case_cluster_bootstrap_95pct_interval": interval,
        "case_clusters": len(deltas),
        "limitations": [
            "Small public AI-authored pilot; domain-expert validation pending",
            "Bootstrap clusters cases; repeats are not independent cases",
            "Quotes can match literally while failing semantic support",
            "Pricing uses supplied uncached input rates; not a billing statement",
            "Cold starts and provider caching can affect latency; no significance claim",
        ],
        "per_run": case_rows,
    }
