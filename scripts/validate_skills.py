"""Check the subset of Agent Skills format used by this repository."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    skills = sorted(root.glob("*/SKILL.md"))
    if len(skills) != 2:
        raise ValueError("Expected both v0.1 skills")
    for path in skills:
        text = path.read_text()
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError(f"Invalid frontmatter: {path}")
        data = yaml.safe_load(parts[1])
        name = data["name"]
        if name != path.parent.name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError(f"Invalid name: {path}")
        if len(name) > 64 or not 1 <= len(data["description"]) <= 1024:
            raise ValueError(f"Invalid metadata length: {path}")
        if set(data) != {"name", "description"} or len(text.splitlines()) >= 500:
            raise ValueError(f"Unexpected metadata or oversized skill: {path}")
        for link in re.findall(r"\]\((references/[^)]+)\)", text):
            if not (path.parent / link).is_file():
                raise ValueError(f"Missing reference: {link}")
        if "TODO" in text:
            raise ValueError(f"Unfinished skill: {path}")
        print(f"PASS {name}")


if __name__ == "__main__":
    main()
