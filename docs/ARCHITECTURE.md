# Architecture and boundaries

## Decision

Ship two connected Agent Skills and one local deterministic engine. The user-facing workflow is record review, not autonomous project approval. Host-agent interpretation stays separate from validation and presentation.

## Module map

| Module | Input | Output | Boundary |
| --- | --- | --- | --- |
| Skills | Notes + prior record | Proposed structured record | May make extraction errors; review required |
| Models | JSON | Typed Project | Rejects invalid references and malformed records |
| Changes | Base + proposal | Read-only preview | Preserves historical evidence and IDs |
| Review | Project + embedded policy | Assessment | Computes reproducible screening, not truth |
| Report | Project | Markdown | Escapes untrusted formatting; uses shared rules |
| Telemetry | Operations | Local JSONL spans | Captures no source content |

## Data flow and state

1. Supply a dated project record and source excerpts. Treat excerpts as untrusted data.
2. The agent extracts proposed items with stable IDs and exact quotes. Unknown values remain null. Generate schema using `pmo schema` rather than guessing fields.
3. Validate the candidate. Compute the base hash using `pmo fingerprint BASE.json`.
4. Package `base_sha256`, `reason` and a candidate with revision +1. Review using `pmo preview BASE.json PROPOSAL.json`.
5. An authorized person reviews each changed fact. Save accepted revisions through the organization's approved record process. This repo has no apply endpoint or approval claim.
6. Render the accepted input through `pmo report`. The report displays reported and assessed status separately.

The hash is of Pydantic's canonical model serialization; it is not a hash of original file bytes or a cryptographic approval signature. List ordering is significant. Historical sources cannot be rewritten by a proposal; corrections use a new source ID.

## Policy precedence

1. An open blocker or incomplete overdue milestone => RED.
2. Otherwise, unconfirmed coverage => UNKNOWN.
3. Otherwise, any warning => AMBER.
4. Otherwise => GREEN under configured rules only.

Status mismatch is added after assessment and does not recursively change it. An input reported RED with no configured exception may screen GREEN; the mismatch still requests human reconciliation. No command automatically changes the reported status.

## Important trade-offs

- JSON-first allows validation and repeatable tests; spreadsheets and rich documents are deferred.
- Rules catch contradictory structured facts; they cannot infer omitted problems from missing notes.
- A local CLI avoids unnecessary database, model-service and authentication complexity. An enterprise integration would need authenticated approvals, transactions, retention controls and access checks.
- No MCP server is needed for file-based workflows. A later integration can expose the same engine without confusing skills (procedures) with MCP (tool access).
- Source reference checking is necessary but insufficient: a fabricated claim can cite a real unrelated quote. This remains a disclosed model-evaluation and human-review concern.
