"""ragproof CLI: validate / init / run / compare / report."""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path

import click

from . import __version__


def _parse_key_values(specs: tuple[str, ...] | list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for spec in specs:
        if "=" not in spec:
            raise click.ClickException(f"expected name=value, got {spec!r}")
        name, raw = spec.split("=", 1)
        if not name.strip():
            raise click.ClickException(f"metric/field name is empty: {spec!r}")
        values[name.strip()] = float(raw.strip().removesuffix("%")) / (100 if raw.strip().endswith("%") else 1)
    return values


@click.group()
@click.version_option(__version__)
def cli():
    """ragproof — RAG evaluation and regression-testing toolkit."""


@cli.command("init")
@click.argument("path", default="ragproof.yaml", type=click.Path())
@click.option("--force", is_flag=True, help="Overwrite an existing starter configuration.")
def init_cmd(path: str, force: bool):
    """Create a starter config and dataset for a new evaluation."""
    config_path = Path(path)
    dataset_path = config_path.parent / "dataset.jsonl"
    if config_path.exists() and not force:
        raise click.ClickException(f"file already exists: {config_path}; use --force to overwrite")
    if not dataset_path.exists() or force:
        dataset_path.write_text(
            json.dumps(
                {
                    "id": "q001",
                    "question": "What is RAG?",
                    "ground_truth": "Retrieval augmented generation.",
                    "tags": ["example"],
                    "difficulty": "easy",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    config_path.write_text(
        """name: my-rag-eval
dataset: dataset.jsonl
adapter:
  type: mock
judge:
  enabled: false
top_ks: [3, 5]
concurrency: 4
""",
        encoding="utf-8",
    )
    click.echo(f"✔ created {config_path} and {dataset_path}")


@cli.command("validate")
@click.option("-c", "--config", "config_path", type=click.Path(exists=True), required=True)
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable validation output.")
def validate_cmd(config_path: str, as_json: bool):
    """Validate configuration and dataset schema without calling the RAG API."""
    from .config import RunConfig
    from .dataset import validate as validate_dataset

    try:
        config = RunConfig.load(config_path)
        errors = config.validation_errors() + validate_dataset(config.dataset)
    except Exception as exc:
        errors = [str(exc)]
    payload = {"valid": not errors, "config": config_path, "errors": errors}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif errors:
        click.echo(f"✘ invalid: {config_path}")
        for error in errors:
            click.echo(f"  - {error}")
        raise click.exceptions.Exit(1)
    else:
        click.echo(f"✔ valid: {config_path}")


@cli.command("dataset-manifest")
@click.argument("path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable manifest output.")
def dataset_manifest_cmd(path: str, as_json: bool):
    """Print a stable dataset manifest for provenance and review."""
    from .dataset import manifest

    try:
        payload = manifest(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(payload, ensure_ascii=False, indent=None if as_json else 2))


@cli.command("dataset-lint")
@click.argument("path", type=click.Path(exists=True))
@click.option("--near-duplicate-threshold", type=float, default=0.9, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def dataset_lint_cmd(path: str, near_duplicate_threshold: float, as_json: bool):
    """Check schema, duplicate IDs/questions, and near-duplicate questions."""
    from .dataset import load, near_duplicate_questions, validate

    errors = validate(path)
    duplicates: list[tuple[str, str, float]] = []
    if not errors:
        duplicates = near_duplicate_questions(load(path), threshold=near_duplicate_threshold)
    payload = {"valid": not errors, "errors": errors, "near_duplicates": duplicates}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        if errors:
            for error in errors:
                click.echo(f"✘ {error}")
        else:
            click.echo(f"✔ dataset schema valid; near duplicates: {len(duplicates)}")
        if duplicates:
            for left, right, score in duplicates:
                click.echo(f"  - {left} ~ {right} ({score:.3f})")
        if errors or duplicates:
            raise click.exceptions.Exit(1)


@cli.command("benchmark-manifest-lint")
@click.argument("path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True)
def benchmark_manifest_lint_cmd(path: str, as_json: bool):
    """Verify benchmark dataset paths, hashes, schemas, and license evidence."""
    from .dataset import validate_benchmark_manifest

    errors = validate_benchmark_manifest(path)
    payload = {"valid": not errors, "manifest": path, "errors": errors}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif errors:
        for error in errors:
            click.echo(f"✘ {error}")
        raise click.exceptions.Exit(1)
    else:
        click.echo(f"✔ benchmark manifest valid: {path}")


@cli.command("trend")
@click.argument("run_paths", nargs=-1, type=click.Path(exists=True))
@click.option("-o", "output", default="trend.json", show_default=True)
@click.option("--metric", "metrics", multiple=True, help="Only include these metrics; repeatable.")
def trend_cmd(run_paths: tuple[str, ...], output: str, metrics: tuple[str, ...]):
    """Summarize multiple runs with bootstrap confidence intervals."""
    from .trend import summarize_runs

    if not run_paths:
        raise click.ClickException("provide at least one run JSON")
    payload = summarize_runs(run_paths, metrics)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".md":
        lines = ["# ragproof trend", "", "| Metric | Count | Latest | Mean | 95% CI |", "|---|---:|---:|---:|---|"]
        for name, item in payload["metrics"].items():
            lines.append(f"| `{name}` | {item['count']} | {item['latest']} | {item['mean']} | {item['ci95_low']} – {item['ci95_high']} |")
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif destination.suffix.lower() == ".html":
        rows = "".join(
            f"<tr><td>{name}</td><td>{item['count']}</td><td>{item['latest']}</td><td>{item['mean']}</td><td>{item['ci95_low']} – {item['ci95_high']}</td></tr>"
            for name, item in payload["metrics"].items()
        )
        destination.write_text(
            "<html><head><meta charset='utf-8'><title>ragproof trend</title></head><body>"
            "<h1>ragproof trend</h1><table border='1'><tr><th>Metric</th><th>Count</th><th>Latest</th><th>Mean</th><th>95% CI</th></tr>"
            + rows
            + "</table></body></html>",
            encoding="utf-8",
        )
    else:
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"✔ trend written to {destination}")


@cli.command("bisect")
@click.argument("run_paths", nargs=-1, type=click.Path(exists=True))
@click.option("--metric", required=True)
@click.option("--threshold", required=True, type=float)
@click.option("--max", "maximum", is_flag=True, help="Treat the metric as lower-is-better.")
def bisect_cmd(run_paths: tuple[str, ...], metric: str, threshold: float, maximum: bool):
    """Find the first run file that crosses a regression gate."""
    from .trend import find_first_regression

    result = find_first_regression(run_paths, metric, threshold, maximum=maximum)
    click.echo(result or "no regression found")


@cli.command("threshold-recommend")
@click.argument("run_paths", nargs=-1, type=click.Path(exists=True))
@click.option("--floor", type=float, default=0.95, show_default=True)
def threshold_recommend_cmd(run_paths: tuple[str, ...], floor: float):
    """Recommend gates from a run history instead of a single baseline."""
    from .trend import recommend_from_history

    if not run_paths:
        raise click.ClickException("provide at least one run JSON")
    click.echo(json.dumps(recommend_from_history(run_paths, floor=floor), ensure_ascii=False, indent=2))


@cli.command("judge-check")
@click.option("-c", "config_path", required=True, type=click.Path(exists=True))
def judge_check_cmd(config_path: str):
    """Check judge endpoint reachability and structured-score parsing."""
    from .config import RunConfig
    from .metrics.judge import Judge

    try:
        config = RunConfig.load(config_path)
        judge = Judge(config.judge)
        result = judge.evaluate_answer_relevancy("What is RAG?", "RAG retrieves context before generation.", "Retrieval augmented generation")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if result is None:
        raise click.ClickException("judge endpoint unavailable or returned an unparseable score")
    click.echo(json.dumps({"score": result.score, "model": result.model, "votes": result.votes}, ensure_ascii=False))


@cli.command("judge-calibrate")
@click.option("--score", "scores", multiple=True, type=float, required=True)
@click.option("--label", "labels", multiple=True, type=float, required=True)
def judge_calibrate_cmd(scores: tuple[float, ...], labels: tuple[float, ...]):
    """Measure Judge calibration against golden scores in the 0–1 range."""
    from .metrics.judge import calibration_summary

    try:
        payload = calibration_summary(list(scores), list(labels))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(payload, ensure_ascii=False))


@cli.command("probe")
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--question", "questions", multiple=True, help="Safe question to send; repeat for a multi-question probe.")
@click.option("-o", "--output", type=click.Path(), help="Write the suggested adapter YAML to this path.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable candidate paths.")
def probe_cmd(config_path: str, questions: tuple[str, ...], output: str | None, as_json: bool):
    """Call an HTTP adapter once and suggest response-field mappings."""
    from .adapters import build_adapter
    from .config import RunConfig
    from .probe import inspect_responses, render_config

    try:
        config = RunConfig.load(config_path)
        if config.adapter.type.lower() == "mock":
            raise click.ClickException("probe requires an HTTP adapter; mock responses already have a known schema")
        probe_questions = questions or ("What is RAG?",)
        responses = [build_adapter(config.adapter).ask(question) for question in probe_questions]
        response = responses[0]
        if response.error:
            raise click.ClickException(f"probe request failed: {response.error}")
        if not isinstance(response.raw, dict):
            raise click.ClickException("probe endpoint did not return a JSON object")
        raw_payloads = [item.raw for item in responses if isinstance(item.raw, dict)]
        mapping = inspect_responses(raw_payloads)
        starter = render_config(config.adapter, mapping)
        if output:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(starter, encoding="utf-8")
        result = {
            "question": probe_questions[0],
            "questions": list(probe_questions),
            "latency_ms": response.latency_ms,
            "latencies_ms": [item.latency_ms for item in responses],
            "streamed": response.streamed,
            "mapping": {key: value for key, value in mapping.items() if key != "candidates"},
            "candidates": mapping["candidates"],
            "output": output,
        }
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False))
    elif output:
        click.echo(f"✔ probe complete ({response.latency_ms:.1f} ms); starter config written to {output}")
        click.echo(json.dumps(result["mapping"], ensure_ascii=False, indent=2))
    else:
        click.echo(f"✔ probe complete ({response.latency_ms:.1f} ms); suggested adapter config:\n\n{starter}")


@cli.command("run")
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("-o", "--output", default="runs/current.json", show_default=True)
@click.option("--no-judge", is_flag=True, help="Disable LLM-as-judge metrics for this run.")
@click.option("--dry-run", is_flag=True, help="Validate and print the execution plan without calling the adapter.")
@click.option("--sample-limit", type=int, help="Evaluate only the first N selected samples.")
@click.option("--include-tag", multiple=True, help="Only evaluate samples carrying this tag; repeatable.")
@click.option("--exclude-tag", multiple=True, help="Skip samples carrying this tag; repeatable.")
@click.option("--require-metric", multiple=True, help="Require a metric for every selected sample; repeatable.")
@click.option("--require-field", multiple=True, help="Require a response field for every selected sample; repeatable.")
@click.option("--min-coverage", multiple=True, help="Minimum coverage gate, e.g. contexts=0.9; repeatable.")
@click.option("--min-sample-count", type=int, help="Require at least this many selected samples.")
@click.option("--stratify-by", type=str, help="Round-robin sample selection by tags, difficulty, answerable, or metadata.FIELD.")
@click.option("--seed", type=int, help="Deterministically shuffle selected samples.")
@click.option("--json", "as_json", is_flag=True, help="Print the run summary as JSON.")
def run_cmd(
    config_path: str,
    output: str,
    no_judge: bool,
    dry_run: bool,
    sample_limit: int | None,
    include_tag: tuple[str, ...],
    exclude_tag: tuple[str, ...],
    require_metric: tuple[str, ...],
    require_field: tuple[str, ...],
    min_coverage: tuple[str, ...],
    min_sample_count: int | None,
    stratify_by: str | None,
    seed: int | None,
    as_json: bool,
):
    """Run the dataset against the configured RAG system and score it."""
    from .config import RunConfig
    from .dataset import load
    from .runner import run

    try:
        config = RunConfig.load(config_path)
        if no_judge:
            config.judge.enabled = False
        if sample_limit is not None:
            config.sample_limit = sample_limit
        if include_tag:
            config.include_tags = list(include_tag)
        if exclude_tag:
            config.exclude_tags = list(exclude_tag)
        if require_metric:
            config.required_metrics = sorted(set(config.required_metrics).union(require_metric))
        if require_field:
            config.required_fields = sorted(set(config.required_fields).union(require_field))
        if min_coverage:
            config.min_coverage.update(_parse_key_values(min_coverage))
        if min_sample_count is not None:
            config.min_sample_count = min_sample_count
        if stratify_by:
            config.stratify_by = stratify_by
        if seed is not None:
            config.seed = seed
        errors = config.validation_errors()
        if errors:
            raise click.ClickException("configuration invalid:\n" + "\n".join(f"- {error}" for error in errors))
        samples = load(config.dataset, reject_duplicates=config.deduplicate_questions)
        if dry_run:
            payload = {"config": config.summary(), "samples_available": len(samples), "top_ks": config.effective_top_ks()}
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else f"✔ dry run: {len(samples)} samples available; top-k={config.effective_top_ks()}")
            return
        report = run(config, output)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
        return
    click.echo(f"✔ {report['sample_count']} samples evaluated → {output}")
    for name, value in report["aggregate"].items():
        click.echo(f"  {name:24s} {value:.3f}")


@cli.command("compare")
@click.option("--baseline", required=True, type=click.Path(exists=True))
@click.option("--current", required=True, type=click.Path(exists=True))
@click.option("--threshold", "thresholds", multiple=True, help="Absolute gate, e.g. faithfulness=0.8.")
@click.option("--max", "max_thresholds", multiple=True, help="Maximum gate for lower-is-better metrics, e.g. error_rate<=0.1.")
@click.option("--min-delta", "min_deltas", multiple=True, help="Minimum current-baseline delta, e.g. recall@5=-0.05.")
@click.option("--max-relative-drop", "relative_drops", multiple=True, help="Maximum relative drop, e.g. faithfulness=5%.")
@click.option("--group-threshold", "group_thresholds", multiple=True, help="Group gate, e.g. tags:zh:faithfulness=0.8.")
@click.option("--group-max", "group_max_thresholds", multiple=True, help="Maximum group gate, e.g. tags:zh:error_rate<=0.1.")
@click.option("--policy", type=click.Path(exists=True), help="YAML/JSON threshold policy file.")
@click.option("--min-sample-count", type=int, help="Require at least this many samples in current run.")
@click.option("--min-coverage", multiple=True, help="Minimum current coverage, e.g. contexts=0.95.")
@click.option("--require-field", multiple=True, help="Require a field at 100% coverage; repeatable.")
@click.option("--allow-provenance-mismatch", is_flag=True, help="Allow runs with different dataset/config fingerprints.")
@click.option("--recommend", is_flag=True, help="Print recommended absolute gates from the baseline.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable comparison output.")
def compare_cmd(
    baseline: str,
    current: str,
    thresholds: tuple[str, ...],
    max_thresholds: tuple[str, ...],
    min_deltas: tuple[str, ...],
    relative_drops: tuple[str, ...],
    group_thresholds: tuple[str, ...],
    group_max_thresholds: tuple[str, ...],
    policy: str | None,
    min_sample_count: int | None,
    min_coverage: tuple[str, ...],
    require_field: tuple[str, ...],
    allow_provenance_mismatch: bool,
    recommend: bool,
    as_json: bool,
):
    """Compare two runs and fail (exit 1) if any gate is not met."""
    from .compare import (
        compare_with_policy,
        load_threshold_policy,
        parse_group_max_thresholds,
        parse_group_thresholds,
        parse_max_thresholds,
        parse_relative_drops,
        parse_thresholds,
        recommend_thresholds,
        results_as_dicts,
    )
    from .policy import GatePolicy

    try:
        if recommend:
            click.echo(json.dumps(recommend_thresholds(baseline), ensure_ascii=False, indent=2))
            from .compare import recommend_max_thresholds

            click.echo(json.dumps({"max": recommend_max_thresholds(baseline)}, ensure_ascii=False, indent=2))
            if not thresholds and not max_thresholds and not min_deltas and not relative_drops:
                return
        parsed = parse_thresholds(list(thresholds))
        parsed_max = parse_max_thresholds(list(max_thresholds))
        parsed_deltas = parse_thresholds(list(min_deltas))
        parsed_relative = parse_relative_drops(list(relative_drops))
        parsed_groups = parse_group_thresholds(list(group_thresholds))
        parsed_group_max = parse_group_max_thresholds(list(group_max_thresholds))
        gate_policy = load_threshold_policy(policy) if policy else GatePolicy()
        gate_policy = gate_policy.merged(
            thresholds=parsed,
            max_thresholds=parsed_max,
            min_deltas=parsed_deltas,
            max_relative_drops=parsed_relative,
            group_thresholds=parsed_groups,
            group_max_thresholds=parsed_group_max,
            min_sample_count=min_sample_count,
            min_coverage=_parse_key_values(min_coverage),
            required_fields=require_field,
            allow_provenance_mismatch=allow_provenance_mismatch,
        )
        results, all_passed = compare_with_policy(baseline, current, gate_policy)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps({"passed": all_passed, "results": results_as_dicts(results)}, ensure_ascii=False))
        if not all_passed:
            sys.exit(1)
        return
    else:
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            click.echo(f"[{status}] {result.metric} ({result.kind}): {result.reason}")
            if not result.passed and os.environ.get("GITHUB_ACTIONS"):
                click.echo(f"::error title=ragproof regression::{result.metric}: {result.reason}")
    if not all_passed:
        click.echo("✘ regression gate failed; inspect the HTML report and failed sample IDs for next steps")
        sys.exit(1)
    click.echo("✔ all thresholds passed")


@cli.command("report")
@click.argument("run_path", type=click.Path(exists=True))
@click.option("-o", "--output", default="report.html", show_default=True)
@click.option("--baseline", type=click.Path(exists=True), help="Embed a baseline/current comparison in the report.")
@click.option("--threshold", "thresholds", multiple=True)
@click.option("--min-delta", "max_deltas", multiple=True)
@click.option("--max-relative-drop", "relative_drops", multiple=True)
@click.option("--max", "max_thresholds", multiple=True)
@click.option("--group-threshold", "group_thresholds", multiple=True)
@click.option("--group-max", "group_max_thresholds", multiple=True)
@click.option("--policy", type=click.Path(exists=True))
@click.option("--min-sample-count", type=int)
@click.option("--min-coverage", multiple=True)
@click.option("--require-field", "required_fields", multiple=True)
@click.option("--allow-provenance-mismatch", is_flag=True)
@click.option("--worst", type=int, help="Show only the N most severe samples in the report.")
@click.option("--open", "open_report", is_flag=True, help="Open the generated report in the default browser.")
def report_cmd(
    run_path: str,
    output: str,
    baseline: str | None,
    thresholds: tuple[str, ...],
    max_deltas: tuple[str, ...],
    relative_drops: tuple[str, ...],
    max_thresholds: tuple[str, ...],
    group_thresholds: tuple[str, ...],
    group_max_thresholds: tuple[str, ...],
    policy: str | None,
    min_sample_count: int | None,
    min_coverage: tuple[str, ...],
    required_fields: tuple[str, ...],
    allow_provenance_mismatch: bool,
    worst: int | None,
    open_report: bool,
):
    """Render a Markdown, HTML, or CSV report from a run JSON."""
    from .report import render

    try:
        out = render(
            run_path,
            output,
            baseline=baseline,
            thresholds=thresholds,
            max_deltas=max_deltas,
            max_relative_drops=relative_drops,
            max_thresholds=max_thresholds,
            group_thresholds=group_thresholds,
            group_max_thresholds=group_max_thresholds,
            policy=policy,
            min_sample_count=min_sample_count,
            min_coverage=min_coverage,
            required_fields=required_fields,
            allow_provenance_mismatch=allow_provenance_mismatch,
            worst=worst,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ report written to {out}")
    if open_report:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    cli()
