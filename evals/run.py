"""Offline development fixtures only; no model accuracy claim."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from pmo_skills.models import Project
from pmo_skills.review import assess


def main() -> int:
    path = Path(__file__).with_name("cases.json")
    cases = json.loads(path.read_text())
    outcomes = []
    times = []
    for case in cases:
        start = time.perf_counter()
        result = assess(Project.model_validate(case["project"]))
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        codes = sorted({f.code for f in result.findings})
        passed = (
            result.assessed_status == case["expected_status"] and codes == case["expected_codes"]
        )
        outcomes.append(
            {
                "case": case["id"],
                "passed": passed,
                "actual_status": result.assessed_status,
                "actual_codes": codes,
            }
        )
    report = {
        "suite": "offline-development-fixtures",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "passed": sum(o["passed"] for o in outcomes),
        "total": len(cases),
        "median_cli_engine_ms": statistics.median(times),
        "max_cli_engine_ms": max(times),
        "model_calls": 0,
        "model_quality_measured": False,
        "results": outcomes,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
