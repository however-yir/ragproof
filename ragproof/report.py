"""Render Markdown, HTML, or CSV reports from a run JSON."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .compare import (
    compare_with_policy,
    parse_group_max_thresholds,
    parse_group_thresholds,
    parse_max_thresholds,
    parse_relative_drops,
    parse_thresholds,
    results_as_dicts,
)
from .policy import GatePolicy
from .schema import load_run

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


def _sample_comparison(baseline: dict, current: dict) -> list[dict]:
    """Return a compact side-by-side view for matching sample IDs."""
    old = {item.get("id"): item for item in baseline.get("results", [])}
    rows = []
    for item in current.get("results", []):
        previous = old.get(item.get("id"))
        if previous is None:
            continue
        rows.append({
            "id": item.get("id"),
            "baseline_answer": previous.get("answer", ""),
            "current_answer": item.get("answer", ""),
            "baseline_metrics": previous.get("metrics", {}),
            "current_metrics": item.get("metrics", {}),
        })
    return rows


def _render_junit(run: dict, output: Path) -> None:
    comparison = run.get("comparison", {}).get("results", [])
    suite = ET.Element("testsuite", name=str(run.get("name", "ragproof")), tests=str(len(run.get("results", [])) + len(comparison)))
    for result in run.get("results", []):
        case = ET.SubElement(suite, "testcase", name=str(result.get("id", "sample")), time=str(float(result.get("latency_ms", 0)) / 1000))
        if result.get("error"):
            failure = ET.SubElement(case, "failure", message=str(result.get("error_type") or "request error"))
            failure.text = str(result.get("error"))
    for gate in comparison:
        case = ET.SubElement(suite, "testcase", classname="ragproof.gates", name=str(gate.get("metric", "gate")))
        if not gate.get("passed"):
            failure = ET.SubElement(case, "failure", message=str(gate.get("kind") or "regression gate"))
            failure.text = str(gate.get("reason"))
    ET.ElementTree(suite).write(output, encoding="utf-8", xml_declaration=True)


def _render_sarif(run: dict, output: Path) -> None:
    results = []
    for item in run.get("comparison", {}).get("results", []):
        if not item.get("passed"):
            results.append({"ruleId": f"ragproof.{item.get('kind', 'gate')}", "level": "error", "message": {"text": f"{item.get('metric')}: {item.get('reason')}"}})
    for item in run.get("results", []):
        if item.get("error"):
            results.append({"ruleId": "ragproof.request", "level": "error", "message": {"text": f"{item.get('id')}: {item.get('error')}"}})
    payload = {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": [{"tool": {"driver": {"name": "ragproof"}}, "results": results}]}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render(
    run_path: str | Path,
    output: str | Path,
    *,
    baseline: str | Path | None = None,
    thresholds: Iterable[str] = (),
    max_deltas: Iterable[str] = (),
    max_relative_drops: Iterable[str] = (),
    max_thresholds: Iterable[str] = (),
    group_thresholds: Iterable[str] = (),
    group_max_thresholds: Iterable[str] = (),
    policy: str | Path | None = None,
    min_sample_count: int | None = None,
    min_coverage: Iterable[str] = (),
    required_fields: Iterable[str] = (),
    allow_provenance_mismatch: bool = False,
    worst: int | None = None,
) -> Path:
    """Render a report; format is inferred from the output extension."""
    run = load_run(run_path)
    run["results"] = _sort_by_severity(run.get("results", []))
    if worst:
        run["results"] = run["results"][:worst]
    out = Path(output)
    fmt = (
        "html" if out.suffix.lower() in (".html", ".htm")
        else "csv" if out.suffix.lower() == ".csv"
        else "xml" if out.suffix.lower() == ".xml"
        else "sarif" if out.suffix.lower() == ".sarif"
        else "md"
    )
    if baseline:
        absolute = parse_thresholds(list(thresholds))
        deltas = parse_thresholds(list(max_deltas)) if max_deltas else {}
        relative = parse_relative_drops(list(max_relative_drops)) if max_relative_drops else {}
        groups = parse_group_thresholds(list(group_thresholds)) if group_thresholds else {}
        maximums = parse_max_thresholds(list(max_thresholds)) if max_thresholds else {}
        group_maximums = parse_group_max_thresholds(list(group_max_thresholds)) if group_max_thresholds else {}
        coverage = parse_thresholds(list(min_coverage)) if min_coverage else {}
        gate_policy = GatePolicy.load(policy) if policy else GatePolicy()
        gate_policy = gate_policy.merged(
            thresholds=absolute,
            max_thresholds=maximums,
            min_deltas=deltas,
            max_relative_drops=relative,
            group_thresholds=groups,
            group_max_thresholds=group_maximums,
            min_sample_count=min_sample_count,
            min_coverage=coverage,
            required_fields=required_fields,
            allow_provenance_mismatch=allow_provenance_mismatch,
        )
        results, passed = compare_with_policy(baseline, run_path, gate_policy)
        run["comparison"] = {"passed": passed, "results": results_as_dicts(results)}
        baseline_data = load_run(baseline)
        run["comparison_samples"] = _sample_comparison(baseline_data, run)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        rows = _csv_rows(run)
        fieldnames = sorted({key for row in rows for key in row})
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return out
    if fmt == "xml":
        _render_junit(run, out)
        return out
    if fmt == "sarif":
        _render_sarif(run, out)
        return out
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=lambda template_name: bool(  # noqa: S701 - only HTML templates are escaped
            template_name and template_name.endswith(".html.j2")
        ),
    )
    template = env.get_template(f"report.{fmt}.j2")
    out.write_text(template.render(run=run), encoding="utf-8")
    return out
