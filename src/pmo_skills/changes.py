"""Revision-aware change previews. Never modify the source record."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from .models import Contract, Project
from .telemetry import operation


def fingerprint(project: Project) -> str:
    return hashlib.sha256(project.model_dump_json().encode()).hexdigest()


class Proposal(Contract):
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    candidate: Project


class Change(Contract):
    path: str
    before: str
    after: str


class Preview(Contract):
    base_sha256: str
    candidate_sha256: str
    reason: str
    changes: list[Change]
    decision: Literal["HUMAN_REVIEW_REQUIRED"] = "HUMAN_REVIEW_REQUIRED"


def preview(base: Project, proposal: Proposal) -> Preview:
    with operation("pmo.preview") as span:
        candidate = proposal.candidate
        if fingerprint(base) != proposal.base_sha256:
            raise ValueError(
                "Base fingerprint mismatch: regenerate the proposal from current records"
            )
        if candidate.project_id != base.project_id or candidate.revision != base.revision + 1:
            raise ValueError("Candidate must retain project_id and increment revision exactly once")
        if candidate.as_of < base.as_of:
            raise ValueError("Candidate reporting date cannot move backwards")
        sources = {s.id: s for s in candidate.sources}
        for source in base.sources:
            if sources.get(source.id) != source:
                raise ValueError("Existing evidence sources are immutable; append a new source ID")
        old = {i.id: i for i in base.items}
        new = {i.id: i for i in candidate.items}
        if not old.keys() <= new.keys():
            raise ValueError("Existing RAID IDs cannot be deleted; close with evidence instead")
        old_milestones = {m.id for m in base.milestones}
        if not old_milestones <= {m.id for m in candidate.milestones}:
            raise ValueError("Existing milestone IDs cannot be deleted")
        changes: list[Change] = []
        for item_id, item in new.items():
            if item_id not in old:
                changes.append(
                    Change(path=f"items/{item_id}", before="(absent)", after=item.model_dump_json())
                )
                continue
            prior = old[item_id]
            if prior.kind != item.kind:
                raise ValueError(
                    "Do not change RAID kind in place; close and create a linked new ID"
                )
            if item.updated_on < prior.updated_on:
                raise ValueError("Item update date cannot move backwards")
            if (
                prior != item
                and prior.evidence == item.evidence
                and (prior.closure_evidence == item.closure_evidence)
            ):
                raise ValueError("Changed items require changed evidence for human review")
            for field in type(item).model_fields:
                before, after = getattr(prior, field), getattr(item, field)
                if before != after:
                    changes.append(
                        Change(
                            path=f"items/{item_id}/{field}", before=str(before), after=str(after)
                        )
                    )
        # Include all non-item fields, including policy changes and appended sources.
        for field in type(base).model_fields:
            if field == "items":
                continue
            before, after = getattr(base, field), getattr(candidate, field)
            if before != after:
                changes.append(Change(path=field, before=str(before), after=str(after)))
        span.set_attribute("pmo.change_count", len(changes))
        return Preview(
            base_sha256=fingerprint(base),
            candidate_sha256=fingerprint(candidate),
            reason=proposal.reason,
            changes=changes,
        )
