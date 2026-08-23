"""Versioned run artifact reader and compatibility migrations."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CURRENT_RUN_SCHEMA_VERSION = 2


def migrate_run(value: dict[str, Any]) -> dict[str, Any]:
    """Return a current in-memory view while preserving all legacy fields."""
    run = deepcopy(value)
    version = run.get("schema_version", 1)
    if not isinstance(version, int) or version < 1:
        raise ValueError("run schema_version must be a positive integer")
    if version > CURRENT_RUN_SCHEMA_VERSION:
        raise ValueError(
            f"run schema_version {version} is newer than supported version {CURRENT_RUN_SCHEMA_VERSION}"
        )
    if version == 1:
        run["schema_version"] = 2
    return run


def validate_run(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("run artifact must be a JSON object")
    run = migrate_run(value)
    for field in ("aggregate", "results"):
        if field not in run:
            run[field] = {} if field == "aggregate" else []
    if not isinstance(run["aggregate"], dict) or not isinstance(run["results"], list):
        raise ValueError("run artifact aggregate/results fields have invalid types")
    return run


def load_run(path: str | Path) -> dict[str, Any]:
    """Load, validate, and migrate a run JSON artifact."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid run JSON: {exc}") from exc
    return validate_run(value)
