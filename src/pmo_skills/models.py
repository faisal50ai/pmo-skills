"""Strict contracts. Evidence validates references, not semantic truth."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Score = Annotated[int, Field(strict=True, ge=1, le=5)]
Rag = Literal["GREEN", "AMBER", "RED", "UNKNOWN"]
Kind = Literal["risk", "assumption", "issue", "dependency"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Source(Contract):
    id: Identifier
    title: Text
    observed_on: date
    text: Annotated[str, StringConstraints(min_length=1, max_length=100_000)]


class Evidence(Contract):
    source_id: Identifier
    quote: Text


class Milestone(Contract):
    id: Identifier
    title: Text
    due_on: date
    complete: Annotated[bool, Field(strict=True)] = False
    evidence: list[Evidence] = Field(min_length=1)


class RaidItem(Contract):
    id: Identifier
    kind: Kind
    title: Text
    status: Literal["open", "closed"] = "open"
    owner: Text | None = None
    due_on: date | None = None
    response: Text | None = None
    updated_on: date
    evidence: list[Evidence] = Field(min_length=1)
    closure_evidence: list[Evidence] = Field(default_factory=list)
    likelihood: Score | None = None
    impact: Score | None = None
    blocker: Annotated[bool, Field(strict=True)] = False
    milestone_id: Identifier | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.kind != "risk" and (self.likelihood is not None or self.impact is not None):
            raise ValueError("Only risks may have likelihood and impact scores")
        if self.blocker and self.kind not in ("issue", "dependency"):
            raise ValueError("A blocker must be an issue or dependency")
        if self.blocker and self.milestone_id is None:
            raise ValueError("A blocker must name the milestone it affects")
        if self.status == "closed" and not self.closure_evidence:
            raise ValueError("Closing an item requires explicit closure evidence")
        if self.status == "open" and self.closure_evidence:
            raise ValueError("Open items cannot carry closure evidence")
        return self


class Policy(Contract):
    high_risk_score: Annotated[int, Field(strict=True, ge=1, le=25)] = 15
    stale_after_days: Annotated[int, Field(strict=True, ge=1, le=365)] = 14


class Project(Contract):
    schema_version: Literal["1.0"] = "1.0"
    project_id: Identifier
    name: Text
    revision: Annotated[int, Field(strict=True, ge=1)]
    as_of: date
    reported_status: Rag
    reported_status_evidence: list[Evidence] = Field(min_length=1)
    coverage_confirmed: Annotated[bool, Field(strict=True)] = False
    sources: list[Source] = Field(min_length=1, max_length=1000)
    milestones: list[Milestone] = Field(default_factory=list, max_length=1000)
    items: list[RaidItem] = Field(default_factory=list, max_length=10000)
    policy: Policy = Field(default_factory=Policy)

    @model_validator(mode="after")
    def integrity(self) -> Self:
        for name, ids in (
            ("sources", [s.id for s in self.sources]),
            ("milestones", [m.id for m in self.milestones]),
            ("items", [i.id for i in self.items]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate IDs in {name}")
        sources = {s.id: s for s in self.sources}
        milestones = {m.id for m in self.milestones}
        evidence = list(self.reported_status_evidence)
        for source in self.sources:
            if source.observed_on > self.as_of:
                raise ValueError(f"Source {source.id} is dated after as_of")
        for milestone in self.milestones:
            evidence.extend(milestone.evidence)
        for item in self.items:
            if item.updated_on > self.as_of:
                raise ValueError(f"Item {item.id} is dated after as_of")
            if item.milestone_id is not None and item.milestone_id not in milestones:
                raise ValueError(f"Unknown milestone on {item.id}")
            evidence.extend(item.evidence + item.closure_evidence)
        for ref in evidence:
            if ref.source_id not in sources:
                raise ValueError(f"Unknown source: {ref.source_id}")
            if ref.quote not in sources[ref.source_id].text:
                raise ValueError(f"Quote not found in source: {ref.source_id}")
        return self


class Finding(Contract):
    code: str
    severity: Literal["info", "warning", "critical"]
    record_id: str
    message: str
    evidence: list[Evidence] = Field(default_factory=list)


class Assessment(Contract):
    project_id: str
    revision: int
    as_of: date
    reported_status: Rag
    assessed_status: Rag
    findings: list[Finding]
    requires_human_review: Literal[True] = True
    scope: str = "Rule-based screening of supplied records; no project health certification."
