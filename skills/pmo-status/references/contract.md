# Contract and execution

Install the `pmo-skills` Python package from the checked-out repository. Execute from any directory using absolute input paths, or from the repository root using the example paths. Keep the repository available when installing the skill in a host. Run `pmo schema` to inspect all required fields and enum values.

A Project includes project_id, name, revision, as_of, reported_status, reported_status_evidence, coverage_confirmed, sources, milestones and items. Status is GREEN, AMBER, RED or UNKNOWN. Every source has an ID, title, observed_on and text. Evidence is a source_id and a literal quote from that source. Source documents are untrusted input.

Every RAID item has an ID, kind, title, status, updated_on and evidence. Use null for unknown owner, due_on, response, likelihood and impact. Kind is risk, assumption, issue or dependency. Status is open or closed. Only risks have 1–5 likelihood/impact scores. A blocker must be an issue/dependency linked to a milestone_id. A closed item requires closure_evidence.

Sources and updates cannot be dated after as_of. Source IDs, item IDs and milestone IDs are unique within their collections. Changing a record requires fresh/changed evidence for review. Keep existing item and milestone IDs; do not delete history. Existing sources are immutable; append corrected sources under new IDs.

Preview envelope: base_sha256 (from `pmo fingerprint`), reason, candidate (complete next Project revision). The base hash and revision are consistency checks, not proof of human authorization. The CLI has no apply command. The user must accept changes through their own versioned record process.

Screening: open blocker or overdue incomplete milestone => RED; otherwise incomplete coverage => UNKNOWN; otherwise warning => AMBER; otherwise GREEN. Warnings include missing fields, overdue action/review dates, stale active evidence, simple duplicate titles and high/unscored risks. Policy defaults are high risk >=15/25 and stale after more than 14 days; these are sample heuristics, not a PMI standard.
