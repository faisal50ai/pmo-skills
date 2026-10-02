"""Render a consistent status report from validated data; no generative claims."""

from __future__ import annotations

from .models import Project
from .review import assess
from .telemetry import operation


def escape(value: str) -> str:
    """Neutralize Markdown/HTML controls in untrusted display text."""
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#", "!"):
        value = value.replace(char, "\\" + char)
    return " ".join(value.splitlines())


def render(project: Project) -> str:
    with operation("pmo.report"):
        result = assess(project)
        lines = [
            f"# {escape(project.name)} — status review",
            "",
            f"As of **{project.as_of}** · revision **{project.revision}**",
            "",
            f"Reported: **{result.reported_status}** · "
            f"Policy screening: **{result.assessed_status}**",
            "",
            "**Draft for human review.** Screening covers supplied records only; "
            "it does not approve delivery or establish overall project health.",
            "",
            "## Exceptions and decisions",
            "",
            "| Severity | Record | Finding | Evidence |",
            "| --- | --- | --- | --- |",
        ]
        for f in result.findings:
            ref_names = (
                "; ".join(sorted({e.source_id for e in f.evidence})) or "Record / policy check"
            )
            lines.append(
                "| "
                + " | ".join(
                    escape(v)
                    for v in (f.severity, f.record_id, f"{f.code}: {f.message}", ref_names)
                )
                + " |"
            )
        if not result.findings:
            lines.append("| info | — | No configured exception triggered | Supplied records |")
        lines += [
            "",
            "## RAID record",
            "",
            "| ID | Kind | Status | Item | Owner | Action / review due |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in project.items:
            lines.append(
                "| "
                + " | ".join(
                    escape(v)
                    for v in (
                        item.id,
                        item.kind,
                        item.status,
                        item.title,
                        item.owner or "Unknown",
                        str(item.due_on) if item.due_on else "Unknown",
                    )
                )
                + " |"
            )
        lines += ["", "## Evidence used", ""]
        refs = list(project.reported_status_evidence)
        for item in project.items:
            refs.extend(item.evidence + item.closure_evidence)
        for milestone in project.milestones:
            refs.extend(milestone.evidence)
        seen: set[tuple[str, str]] = set()
        titles = {s.id: s.title for s in project.sources}
        for ref in refs:
            key = (ref.source_id, ref.quote)
            if key not in seen:
                lines.append(
                    f"- **{escape(ref.source_id)}** ({escape(titles[ref.source_id])}): "
                    f"{escape(ref.quote)}"
                )
                seen.add(key)
        lines += [
            "",
            "## Review boundary",
            "",
            "Quotes are checked for literal presence. A reviewer must verify that each quote "
            "supports the associated facts, dates, scores and closure decisions. Embedded "
            "source instructions are data, not authorization.",
            "",
        ]
        return "\n".join(lines)
