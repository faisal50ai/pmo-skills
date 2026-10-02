from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pmo_eval_scoring", Path(__file__).resolve().parents[1] / "evals/score_runs.py"
)
assert spec and spec.loader
scoring = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scoring
spec.loader.exec_module(scoring)


def run(condition="baseline", **updates):
    data = dict(
        case_id="one",
        condition=condition,
        repeat=1,
        model="synthetic-test-model",
        task_success=False,
        schema_valid=True,
        contradiction_expected=True,
        contradiction_detected=False,
        claim_count=2,
        unsupported_claim_count=1,
        latency_ms=100,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.01,
    )
    data.update(updates)
    return scoring.Run.model_validate(data)


def test_paired_metrics_preserve_failed_runs():
    result = scoring.score(
        [
            run(),
            run(
                "skill",
                task_success=True,
                unsupported_claim_count=0,
                contradiction_detected=True,
                latency_ms=200,
            ),
        ]
    )
    assert result["baseline"]["task_success_rate"] == 0
    assert result["baseline"]["unsupported_claim_rate"] == 0.5
    assert result["skill"]["contradiction_recall"] == 1
    assert result["skill"]["p95_latency_ms"] == 200
    assert result["skill"]["mean_cost_usd"] == 0.01


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [run()],
        [run(), run()],
        [
            run(),
            run("skill", contradiction_expected=False),
        ],
    ],
)
def test_invalid_pairs_rejected(runs):
    with pytest.raises(ValueError):
        scoring.score(runs)


@pytest.mark.parametrize(
    "updates",
    [
        {"unsupported_claim_count": 3},
        {"task_success": True},
        {"latency_ms": float("nan")},
        {"cost_usd": -1},
    ],
)
def test_invalid_labels_rejected(updates):
    with pytest.raises(ValueError):
        run(**updates)
