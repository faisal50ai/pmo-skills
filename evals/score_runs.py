"""Score human-labeled paired model runs; does not run or judge a model."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from pmo_skills.models import Contract, Text


class Run(Contract):
    case_id: Text
    condition: Literal["baseline", "skill"]
    repeat: Annotated[int, Field(strict=True, ge=1)]
    model: Text
    task_success: Annotated[bool, Field(strict=True)]
    schema_valid: Annotated[bool, Field(strict=True)]
    contradiction_expected: Annotated[bool, Field(strict=True)]
    contradiction_detected: Annotated[bool, Field(strict=True)]
    claim_count: Annotated[int, Field(strict=True, ge=0)]
    unsupported_claim_count: Annotated[int, Field(strict=True, ge=0)]
    latency_ms: Annotated[float, Field(ge=0)]
    input_tokens: Annotated[int, Field(strict=True, ge=0)]
    output_tokens: Annotated[int, Field(strict=True, ge=0)]
    cost_usd: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def coherent(self) -> Run:
        if self.unsupported_claim_count > self.claim_count:
            raise ValueError("Unsupported claims exceed total claims")
        if self.task_success and (not self.schema_valid or self.unsupported_claim_count):
            raise ValueError("Task success requires valid schema and no unsupported claims")
        if self.task_success and self.contradiction_expected != self.contradiction_detected:
            raise ValueError("Task success requires correct contradiction detection")
        return self


def score(runs: list[Run]) -> dict[str, object]:
    if not runs:
        raise ValueError("No runs supplied")
    if len({r.model for r in runs}) != 1:
        raise ValueError("Score each model separately; do not pool model results")
    pairs: dict[tuple[str, int, str], dict[str, Run]] = {}
    for run in runs:
        key = (run.case_id, run.repeat, run.model)
        pair = pairs.setdefault(key, {})
        if run.condition in pair:
            raise ValueError("Duplicate case/condition/repeat/model")
        pair[run.condition] = run
    for pair in pairs.values():
        if set(pair) != {"baseline", "skill"}:
            raise ValueError("Every run requires a matching baseline/skill pair")
        if pair["baseline"].contradiction_expected != pair["skill"].contradiction_expected:
            raise ValueError("Contradiction labels differ within pair")
    report: dict[str, object] = {
        "paired_runs": len(pairs),
        "models": sorted({r.model for r in runs}),
    }
    for condition in ("baseline", "skill"):
        group = [r for r in runs if r.condition == condition]
        claims = sum(r.claim_count for r in group)
        positive = [r for r in group if r.contradiction_expected]
        latencies = sorted(r.latency_ms for r in group)
        report[condition] = {
            "n": len(group),
            "task_success_rate": sum(r.task_success for r in group) / len(group),
            "schema_valid_rate": sum(r.schema_valid for r in group) / len(group),
            "unsupported_claim_rate": sum(r.unsupported_claim_count for r in group) / claims
            if claims
            else None,
            "contradiction_recall": sum(r.contradiction_detected for r in positive) / len(positive)
            if positive
            else None,
            "false_positive_count": sum(
                r.contradiction_detected and not r.contradiction_expected for r in group
            ),
            "p50_latency_ms": statistics.median(latencies),
            "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1],
            "mean_cost_usd": sum(r.cost_usd for r in group) / len(group),
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in group),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    args = parser.parse_args()
    try:
        runs = [
            Run.model_validate_json(line)
            for line in args.runs.read_text().splitlines()
            if line.strip()
        ]
        print(json.dumps(score(runs), indent=2))
        return 0
    except (ValueError, OSError):
        print("Invalid run file: check schema, numeric bounds and matching pairs.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
