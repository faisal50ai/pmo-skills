# Evaluation protocol

## Offline suite

`python evals/run.py` loads labeled synthetic cases and compares expected status and the complete finding-code set. Fixtures are development/regression cases, not a held-out model benchmark. Timing excludes interpreter startup and model work. Results include Python version, platform and suite hash.

`pytest -q` also checks malformed inputs, date boundaries, closure evidence, stale base hashes, attempts to remove history, escaping, CLI errors and trace content. Rule test success does not establish LLM accuracy.

## Paired model study

Use the same model/version, inference settings, tool availability and source bundles for both conditions. Baseline gets the task and output schema; treatment additionally gets the relevant skill and its references. Randomize order, use repeated runs and keep development cases separate from a locked evaluation set. Do not include expected answers in the model prompt.

For RAID extraction, obtain independently reviewed labels for kind, owner, dates, exact evidence support and required clarification. For status reviews, include GREEN/RED contradictions, incomplete coverage, stale notes and closed blockers. Include benign and injected instructions in source notes. Count malformed output and refusals; do not drop failed runs.

Report exact field accuracy, unsupported claim rate, contradiction recall, schema validity and task success. Human-label semantic evidence support; neither literal matching nor an LLM judge alone proves factuality. Report per-scenario outcomes and sample sizes, not just an aggregate percentage.

## Scoring recorded runs

Create JSONL records with fields:

```json
{"case_id":"case-01","condition":"baseline","repeat":1,"model":"record-exact-model-version","task_success":false,"schema_valid":true,"contradiction_expected":true,"contradiction_detected":false,"claim_count":4,"unsupported_claim_count":1,"latency_ms":1500,"input_tokens":700,"output_tokens":200,"cost_usd":0.001}
```

Add a corresponding `condition: "skill"` record with the same case, repeat, model and expected-contradiction label. Record actual usage and the pricing basis used to calculate cost in the study notes. `evals/score_runs.py` validates complete pairs and emits condition metrics. It does not call a provider, infer missing values, or grade outputs automatically.

The host controls rate limits and token budgets. Set an explicit per-run output limit, maximum retries and total study spend before executing paid runs. Trace model/tool calls through the host's instrumentation; this package traces its deterministic engine only.

## Validation record

Local Python tests, formatting, type checks, skill validation and the offline suite are run before the initial commit. See committed `evals/results.json` for measured offline outcomes. Live provider baselines and cross-client installation tests have not been run. Docker configuration is provided; Docker is unavailable in the build environment, so a local container build has not been verified. GitHub Actions [run 37051631669](https://github.com/faisal50ai/pmo-skills/actions/runs/37051631669) passed both Python 3.11/3.12 jobs and the Docker build/CLI smoke test.

### Initial local run — 2026-10-02

Python 3.12.14: 53 pytest tests passed; 16/16 deterministic development fixtures passed. Ruff lint/format, strict mypy and both skill-contract checks passed. See `evals/results.json` for engine-only timings and the fixture hash.

A separate agent read `pmo-status/SKILL.md`, ran validate/review/report on the synthetic example, and surfaced the reported GREEN versus screened RED contradiction, blocker I1 and high risk R1. This is one qualitative forward test with tool execution, not a comparative model benchmark. No model latency, token usage or cost was captured. The RAID skill has contract and engine coverage but has not yet had an independent extraction study.
