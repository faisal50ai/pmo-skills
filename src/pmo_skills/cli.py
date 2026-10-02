"""Local CLI; no external calls or source-file mutations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from . import telemetry
from .changes import Proposal, fingerprint, preview
from .models import Project
from .report import render
from .review import assess

MAX_BYTES = 5_000_000


def read_text(path: Path) -> str:
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Input exceeds the 5 MB limit")
    return content.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, help="Write safe OpenTelemetry spans to a NEW file")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "review", "report", "fingerprint"):
        command = commands.add_parser(name)
        command.add_argument("project", type=Path)
    command = commands.add_parser("preview")
    command.add_argument("project", type=Path)
    command.add_argument("proposal", type=Path)
    commands.add_parser("schema")
    args = parser.parse_args(argv)
    try:
        if args.trace:
            telemetry.configure(args.trace)
        with telemetry.operation("pmo.command") as span:
            span.set_attribute("pmo.command", args.command)
            if args.command == "schema":
                output = json.dumps(Project.model_json_schema(), indent=2)
            else:
                with telemetry.operation("pmo.validate"):
                    project = Project.model_validate_json(read_text(args.project))
                if args.command == "validate":
                    output = json.dumps({"valid": True, "sha256": fingerprint(project)})
                elif args.command == "fingerprint":
                    output = fingerprint(project)
                elif args.command == "report":
                    output = render(project)
                elif args.command == "preview":
                    proposal = Proposal.model_validate_json(read_text(args.proposal))
                    output = preview(project, proposal).model_dump_json(indent=2)
                else:
                    output = assess(project).model_dump_json(indent=2)
            print(output)
        return 0
    except ValidationError as exc:
        # Do not echo source text or input values into logs.
        errors = [
            {"location": list(e["loc"]), "type": e["type"]}
            for e in exc.errors(include_input=False, include_context=False, include_url=False)
        ]
        print(json.dumps({"error": "invalid_contract", "details": errors}), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    finally:
        telemetry.close()


if __name__ == "__main__":
    raise SystemExit(main())
