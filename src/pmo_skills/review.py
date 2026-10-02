"""Deterministic policy checks shared by both skills."""

from __future__ import annotations

from .models import Assessment, Evidence, Finding, Project, Rag
from .telemetry import operation


def assess(project: Project) -> Assessment:
    with operation("pmo.assess") as span:
        findings: list[Finding] = []

        def add(
            code: str, severity: str, record_id: str, message: str, evidence: list[Evidence]
        ) -> None:
            findings.append(
                Finding.model_validate(
                    {
                        "code": code,
                        "severity": severity,
                        "record_id": record_id,
                        "message": message,
                        "evidence": evidence,
                    }
                )
            )

        if not project.coverage_confirmed:
            add(
                "COVERAGE_UNCONFIRMED",
                "warning",
                project.project_id,
                "Completeness of the supplied RAID record has not been confirmed.",
                [],
            )
        for milestone in project.milestones:
            if not milestone.complete and milestone.due_on < project.as_of:
                add(
                    "MILESTONE_OVERDUE",
                    "critical",
                    milestone.id,
                    "An incomplete milestone is overdue.",
                    milestone.evidence,
                )
        seen: dict[tuple[str, str], str] = {}
        for item in project.items:
            normalized = (item.kind, " ".join(item.title.casefold().split()))
            if normalized in seen:
                add(
                    "POSSIBLE_DUPLICATE",
                    "warning",
                    item.id,
                    f"Same kind and normalized title as {seen[normalized]}; review before merging.",
                    item.evidence,
                )
            else:
                seen[normalized] = item.id
            if item.status == "closed":
                continue
            if item.blocker:
                add(
                    "OPEN_BLOCKER",
                    "critical",
                    item.id,
                    f"Unresolved blocker affects milestone {item.milestone_id}.",
                    item.evidence,
                )
            for field, missing in (
                ("owner", item.owner is None),
                ("due_on", item.due_on is None),
                ("response", item.response is None),
            ):
                if missing:
                    add(
                        "MISSING_" + field.upper(),
                        "warning",
                        item.id,
                        f"Open item has no {field}; request clarification.",
                        item.evidence,
                    )
            if item.due_on and item.due_on < project.as_of:
                add(
                    "ACTION_OVERDUE",
                    "warning",
                    item.id,
                    "Open item's action/review date is overdue.",
                    item.evidence,
                )
            if (project.as_of - item.updated_on).days > project.policy.stale_after_days:
                add(
                    "STALE_ITEM",
                    "warning",
                    item.id,
                    "Open item needs a fresh update.",
                    item.evidence,
                )
            if item.kind == "risk":
                if item.likelihood is None or item.impact is None:
                    add(
                        "UNSCORED_RISK",
                        "warning",
                        item.id,
                        "Risk likelihood or impact is unknown; do not invent a score.",
                        item.evidence,
                    )
                elif item.likelihood * item.impact >= project.policy.high_risk_score:
                    add(
                        "HIGH_RISK",
                        "warning",
                        item.id,
                        f"Risk score {item.likelihood * item.impact}/25 "
                        "reaches the policy threshold.",
                        item.evidence,
                    )
        # Stale evidence cannot silently support a green assessment.
        refs = [*project.reported_status_evidence]
        for m in project.milestones:
            if not m.complete:
                refs.extend(m.evidence)
        for i in project.items:
            if i.status == "open":
                refs.extend(i.evidence)
        active_sources = {ref.source_id for ref in refs}
        for source in project.sources:
            if (
                source.id in active_sources
                and (project.as_of - source.observed_on).days > project.policy.stale_after_days
            ):
                add(
                    "STALE_SOURCE",
                    "warning",
                    source.id,
                    "An active evidence source is older than the freshness threshold.",
                    [],
                )
        assessed: Rag
        if any(f.severity == "critical" for f in findings):
            assessed = "RED"
        elif not project.coverage_confirmed:
            assessed = "UNKNOWN"
        elif findings:
            assessed = "AMBER"
        else:
            assessed = "GREEN"
        if project.reported_status != assessed:
            add(
                "STATUS_MISMATCH",
                "warning",
                project.project_id,
                f"Reported {project.reported_status}; policy screening yields {assessed}. "
                "Reconcile the difference with the project owner.",
                project.reported_status_evidence,
            )
        span.set_attribute("pmo.finding_count", len(findings))
        span.set_attribute("pmo.assessed_status", assessed)
        return Assessment(
            project_id=project.project_id,
            revision=project.revision,
            as_of=project.as_of,
            reported_status=project.reported_status,
            assessed_status=assessed,
            findings=findings,
        )
