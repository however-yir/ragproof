"""ragproof CLI: validate / init / run / compare / report."""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path

import click

from . import __version__


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


@cli.command("run")
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("-o", "--output", default="runs/current.json", show_default=True)
@click.option("--no-judge", is_flag=True, help="Disable LLM-as-judge metrics for this run.")
@click.option("--dry-run", is_flag=True, help="Validate and print the execution plan without calling the adapter.")
@click.option("--sample-limit", type=int, help="Evaluate only the first N selected samples.")
@click.option("--include-tag", multiple=True, help="Only evaluate samples carrying this tag; repeatable.")
@click.option("--exclude-tag", multiple=True, help="Skip samples carrying this tag; repeatable.")
@click.option("--require-metric", multiple=True, help="Require a metric for every selected sample; repeatable.")
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
        if seed is not None:
            config.seed = seed
        errors = config.validation_errors()
        if errors:
            raise click.ClickException("configuration invalid:\n" + "\n".join(f"- {error}" for error in errors))
        samples = load(config.dataset)
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
@click.option("--min-delta", "min_deltas", multiple=True, help="Minimum current-baseline delta, e.g. recall@5=-0.05.")
@click.option("--max-relative-drop", "relative_drops", multiple=True, help="Maximum relative drop, e.g. faithfulness=5%.")
@click.option("--group-threshold", "group_thresholds", multiple=True, help="Group gate, e.g. tags:zh:faithfulness=0.8.")
@click.option("--allow-provenance-mismatch", is_flag=True, help="Allow runs with different dataset/config fingerprints.")
@click.option("--recommend", is_flag=True, help="Print recommended absolute gates from the baseline.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable comparison output.")
def compare_cmd(
    baseline: str,
    current: str,
    thresholds: tuple[str, ...],
    min_deltas: tuple[str, ...],
    relative_drops: tuple[str, ...],
    group_thresholds: tuple[str, ...],
    allow_provenance_mismatch: bool,
    recommend: bool,
    as_json: bool,
):
    """Compare two runs and fail (exit 1) if any gate is not met."""
    from .compare import (
        compare,
        parse_group_thresholds,
        parse_relative_drops,
        parse_thresholds,
        recommend_thresholds,
        results_as_dicts,
    )

    try:
        if recommend:
            click.echo(json.dumps(recommend_thresholds(baseline), ensure_ascii=False, indent=2))
            if not thresholds and not min_deltas and not relative_drops:
                return
        parsed = parse_thresholds(list(thresholds))
        parsed_deltas = parse_thresholds(list(min_deltas))
        parsed_relative = parse_relative_drops(list(relative_drops))
        parsed_groups = parse_group_thresholds(list(group_thresholds))
        results, all_passed = compare(
            baseline,
            current,
            parsed,
            min_deltas=parsed_deltas,
            max_relative_drops=parsed_relative,
            group_thresholds=parsed_groups,
            allow_provenance_mismatch=allow_provenance_mismatch,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps({"passed": all_passed, "results": results_as_dicts(results)}, ensure_ascii=False))
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
@click.option("--group-threshold", "group_thresholds", multiple=True)
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
    group_thresholds: tuple[str, ...],
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
            group_thresholds=group_thresholds,
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
