"""Validate repository-owned Action metadata and issue forms."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTION = re.compile(r"^[^./][^@]*@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML object")
    return value


def _validate_pins() -> list[str]:
    errors: list[str] = []
    for path in [*ROOT.glob(".github/**/*.yml"), *ROOT.glob(".github/**/*.yaml")]:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = re.match(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", line)
            if match and not match.group(1).startswith("./") and not PINNED_ACTION.fullmatch(match.group(1)):
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: action is not pinned to a full SHA")
    return errors


def _validate_action() -> list[str]:
    path = ROOT / ".github" / "actions" / "evaluate" / "action.yml"
    action = _load(path)
    errors = [f"action.yml missing {field}" for field in ("name", "description", "runs") if field not in action]
    steps = action.get("runs", {}).get("steps", [])
    step_ids = {step.get("id") for step in steps if isinstance(step, dict)}
    for name, output in action.get("outputs", {}).items():
        value = str(output.get("value", "")) if isinstance(output, dict) else ""
        match = re.search(r"steps\.([\w-]+)\.outputs", value)
        if match and match.group(1) not in step_ids:
            errors.append(f"action output {name} references missing step id {match.group(1)}")
    return errors


def _validate_issue_forms() -> list[str]:
    errors: list[str] = []
    forms = (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")
    for path in forms:
        if path.name == "config.yml":
            continue
        form = _load(path)
        for field in ("name", "description", "body"):
            if field not in form:
                errors.append(f"{path.relative_to(ROOT)} missing {field}")
        if not isinstance(form.get("body"), list) or not form["body"]:
            errors.append(f"{path.relative_to(ROOT)} body must be a non-empty list")
    return errors


def main() -> None:
    errors = [*_validate_pins(), *_validate_action(), *_validate_issue_forms()]
    if errors:
        raise SystemExit("\n".join(errors))
    print("GitHub Actions metadata and issue forms are valid")


if __name__ == "__main__":
    main()
