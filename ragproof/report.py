"""Render Markdown, HTML, or CSV reports from a run JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader

from .compare import compare, parse_relative_drops, parse_thresholds, results_as_dicts

_TEMPLATES = Path(__file__).parent / "templates"


def _csv_rows(run: dict) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in run.get("results", []):
        row: dict[str, object] = {
            "id": result.get("id"),
            "question": result.get("question"),
            "answer": result.get("answer"),
            "error": result.get("error"),
            "error_type": result.get("error_type"),
            "latency_ms": result.get("latency_ms"),
            "tags": ",".join(result.get("tags", [])),
            "difficulty": result.get("difficulty"),
        }
        row.update(result.get("metrics", {}))
        rows.append(row)
    return rows


def _sort_by_severity(results: list[dict]) -> list[dict]:
    """Put request failures and low-scoring samples first for triage."""
    return sorted(
        results,
        key=lambda result: (
            0 if result.get("error") else 1,
            min((value for value in result.get("metrics", {}).values() if value is not None), default=1.0),
        ),
    )


def render(
    run_path: str | Path,
    output: str | Path,
    *,
    baseline: str | Path | None = None,
    thresholds: Iterable[str] = (),
    max_deltas: Iterable[str] = (),
    max_relative_drops: Iterable[str] = (),
    worst: int | None = None,
) -> Path:
    """Render a report; format is inferred from the output extension."""
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    run["results"] = _sort_by_severity(run.get("results", []))
    if worst:
        run["results"] = run["results"][:worst]
    out = Path(output)
    fmt = "html" if out.suffix.lower() in (".html", ".htm") else "csv" if out.suffix.lower() == ".csv" else "md"
    if baseline:
        absolute = parse_thresholds(list(thresholds))
        deltas = parse_thresholds(list(max_deltas)) if max_deltas else {}
        relative = parse_relative_drops(list(max_relative_drops)) if max_relative_drops else {}
        results, passed = compare(baseline, run_path, absolute, min_deltas=deltas, max_relative_drops=relative)
        run["comparison"] = {"passed": passed, "results": results_as_dicts(results)}
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        rows = _csv_rows(run)
        fieldnames = sorted({key for row in rows for key in row})
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return out
    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=(fmt == "html"))
    template = env.get_template(f"report.{fmt}.j2")
    out.write_text(template.render(run=run), encoding="utf-8")
    return out
