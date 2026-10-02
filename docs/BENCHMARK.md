# Paired instruction probe

This runner compares the same model and source bundle with and without the relevant PMO skill instructions. It tests field extraction and status screening in isolation. It does **not** test skill discovery, tool execution, approvals, state recovery or a complete agent workflow.

## Current evidence

Ten public, AI-authored synthetic cases cover missing ownership, explicit assignments, dependencies, closure requests without verification, source instructions, conflicting deadlines, status contradictions, coverage gaps, closed blockers and a clean negative control. Labels are provisional; independent PMO expert review is pending. These cases are a pilot set, not a private holdout or representative production sample.

The runner and scorer have offline regression tests, including tests through the actual OpenAI SDK with HTTP transport mocked. No live model comparison has been run. No model-quality uplift, latency or cost result is claimed.

## Study controls

- Both conditions receive identical tasks, output schema, source notes, policy rules, model and output-token cap. The treatment adds the complete selected `SKILL.md` and contract reference.
- Baseline already includes sensible source-grounding and unknown-value instructions. It is not intentionally weakened.
- The benchmark output format replaces the skills' complete-artifact requirement equally in both conditions. No tools are exposed. This is an instruction ablation, not a pack-level effectiveness claim.
- Three repeats per case produce 30 pairs / 60 requests by default. Pair order and within-pair condition order are seeded and randomized. Repeats remain correlated with their source case.
- Preparation copies and hashes the cases, labels, skill text, schema and requests. Expected labels are never added to model input. Requests include only questions and source notes.
- Use an exact model snapshot if the provider offers one. Record the requested and returned model IDs, SDK version, reasoning setting, token usage, cache usage, timestamps, pricing basis and response IDs. Runs with mixed returned model IDs do not produce a paired comparison.
- Preparation is network-free. Execution is explicit. CI runs mock tests only; it has no model credential and does not run paid evaluations.

## Prepare a study

From the repository root:

```bash
python -m pip install -e '.[benchmark]'
read -r -p 'Exact model ID: ' PMO_MODEL
read -r -p 'Uncached input USD per million tokens: ' PMO_INPUT_PRICE
read -r -p 'Output USD per million tokens: ' PMO_OUTPUT_PRICE
read -r -p 'Pricing reference URL and date checked: ' PMO_PRICE_REFERENCE
read -r -p 'Maximum estimated study spend in USD: ' PMO_MAX_COST
python -m pmo_skills.benchmark prepare \
  --out private/pilot \
  --model "$PMO_MODEL" \
  --input-per-million "$PMO_INPUT_PRICE" \
  --output-per-million "$PMO_OUTPUT_PRICE" \
  --pricing-reference "$PMO_PRICE_REFERENCE" \
  --max-cost-usd "$PMO_MAX_COST"
```

Use a Responses API model supporting strict JSON Schema. There is no hidden model default or automatic fallback. Add `--reasoning-effort` only if supported by your chosen model. The manifest records this setting; when omitted, the model's default applies equally to both conditions. Check the prepared `manifest.json` before running. The study directory must be new; existing results are never overwritten.

`--max-requests`, `--max-output-tokens`, `--repeats` and `--seed` are explicit controls. The initial spend reserve uses UTF-8 input byte length, schema length, an overhead allowance and the output cap. This is a conservative **estimate**, not a guaranteed billing ceiling. Configure provider-side spend controls too; check whether those are enforced caps or alerts. Estimated realized cost uses reported token counts and your supplied uncached input/output prices. Cache discounts are not applied, and unknown billing after failed requests is not treated as zero.

## Execute once

Set `OPENAI_API_KEY` through your local secret manager or environment, outside source control. Do not put it in a command argument, file committed to GitHub, or chat message.

```bash
python -m pmo_skills.benchmark run private/pilot
python -m pmo_skills.benchmark score private/pilot > private/pilot/metrics.json
python -m pmo_skills.benchmark review-packet private/pilot > private/pilot/review.json
```

The runner uses the official OpenAI Responses endpoint with `store=False`, sequential async requests, a per-request timeout and **zero automatic retries**. A rate limit, API failure, missing usage or an exceeded cost reserve stops subsequent requests; each unattempted slot is recorded as skipped. The request limit therefore also limits attempts. There is no silent model fallback or repair pass. Refusals, invalid outputs and truncation remain failures in the planned denominator.

Every completed request is flushed to `runs.jsonl`. Do not resume or rerun an existing study automatically: after a connection failure, a request may have incurred cost even without a response. Create a new study after investigation. Interrupted studies with missing rows fail scoring rather than silently dropping records. Exit 1 signals an aborted run; exit 2 signals configuration or integrity errors.

`trace.jsonl` contains local OpenTelemetry operation/status/token-count spans. It excludes source text, answers, credentials, model IDs and response IDs. The study files contain prompts and outputs, so keep them private and share only reviewed, sanitized records. `private/` is ignored by git. `store=False` does not itself promise zero provider retention; consult your account's data controls.

## Read the metrics correctly

| Metric | Meaning and boundary |
| --- | --- |
| Field accuracy | Normalized exact match to provisional labels; missing/invalid answers score zero. Case and whitespace are normalized, not paraphrases or dates. |
| Valid answer set | Correct schema plus exactly one answer per requested question ID. |
| Literal evidence pass | Non-null answers have quotes found in supplied sources. Does not establish entailment. |
| Contradiction recall / false positives | Detection on the four status cases; sample size is reported. |
| Paired accuracy delta | Treatment minus baseline, averaged within each case across repeats, then across cases. |
| Bootstrap interval | 2,000 seeded resamples of case clusters, not individual repeated runs; exploratory on ten cases. No significance or generalization claim. |
| Semantic support | Human labels only. Unreviewed results stay unknown. Coverage and unclear judgments are reported separately. |
| Latency | Observed request wall time, including client/network work; cold starts and caching affect it. Skipped requests have no latency. |
| Cost | Sum of known usage-based estimates, with completeness flagged; not an invoice. |

If a run is interrupted or returned model IDs differ, the paired delta and interval are suppressed. Per-run outcomes and planned denominators remain visible for diagnosis. Review per-skill and per-scenario outcomes; a mixed pack aggregate alone does not describe a production workload.

## Blinded semantic review

Give reviewers **only** `review.json`. It omits model, condition, repeat and expected labels; opaque response IDs allow later joining. It is randomized separately from execution order. The study owner can recover condition mapping, so this is a reviewer-blinding procedure, not cryptographic concealment.

For each answer, including nulls, ask whether the source meaning supports that decision:

- **supported:** the source establishes the value, or the fact is genuinely unknown/ambiguous when null is returned;
- **unsupported:** the answer invents, contradicts or unjustifiably infers the fact;
- **unclear:** the supplied context is insufficient for the reviewer to decide.

A speaker is not necessarily an owner. A request to close is not verification. A mentioned date is not necessarily an agreed action deadline. Quote presence alone earns no semantic credit.

Return a JSON array containing `review_id`, `reviewer`, and `judgments` with `id`, `support`, and a nonempty `reason` for every answer. Annotations must cover each reviewed response completely; partial response annotations are rejected. Partial coverage across responses is allowed and reported explicitly.

```bash
python -m pmo_skills.benchmark score private/pilot \
  --annotations private/pilot/annotations.json > private/pilot/reviewed-metrics.json
```

Have two independent PMO reviewers label a subset and reconcile disagreements before interpreting results. The current scorer accepts one adjudicated label per answer; it does not calculate inter-rater agreement. Unsupported-claim rate uses reviewed non-null answers only; field accuracy separately penalizes incorrect abstentions. Never describe partial reviewed coverage as the whole model's unsupported-claim rate.

## Next evidence gate

1. Independently review and freeze a private holdout before tuning the prompts on it.
2. Run the pilot on a chosen model snapshot with approved pricing and budget.
3. Preserve all outcomes and disclose any interrupted attempts.
4. Obtain semantic review, publish per-case failures, and compare against baseline without assuming improvement.
5. Separately test full skill discovery, commands, generated artifacts and human review in the intended agent host.

## Sources

- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [Testing Agent Skills systematically](https://developers.openai.com/blog/eval-skills)
