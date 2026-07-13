"""ragproof CLI: run / compare / report."""

from __future__ import annotations

import sys

import click

from . import __version__


@click.group()
@click.version_option(__version__)
def cli():
    """ragproof — RAG evaluation and regression-testing toolkit."""


@cli.command("run")
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("-o", "--output", default="runs/current.json", show_default=True)
@click.option("--no-judge", is_flag=True, help="Disable LLM-as-judge metrics for this run.")
def run_cmd(config_path: str, output: str, no_judge: bool):
    """Run the dataset against the configured RAG system and score it."""
    from .config import RunConfig
    from .runner import run

    config = RunConfig.load(config_path)
    if no_judge:
        config.judge.enabled = False
    report = run(config, output)
    click.echo(f"✔ {report['sample_count']} samples evaluated → {output}")
    for name, value in report["aggregate"].items():
        click.echo(f"  {name:20s} {value:.3f}")


@cli.command("compare")
@click.option("--baseline", required=True, type=click.Path(exists=True))
@click.option("--current", required=True, type=click.Path(exists=True))
@click.option(
    "--threshold",
    "thresholds",
    multiple=True,
    help="Metric gate, e.g. --threshold faithfulness=0.8 --threshold recall@5=0.7",
)
def compare_cmd(baseline: str, current: str, thresholds: tuple[str, ...]):
    """Compare two runs and fail (exit 1) if any threshold is not met."""
    from .compare import compare, parse_thresholds

    parsed = parse_thresholds(list(thresholds))
    results, all_passed = compare(baseline, current, parsed)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        delta = ""
        if r.current is not None and r.baseline is not None:
            delta = f" (baseline {r.baseline:.3f}, Δ{r.current - r.baseline:+.3f})"
        click.echo(f"[{status}] {r.metric}: {r.reason}{delta}")
    if not all_passed:
        click.echo("✘ regression gate failed")
        sys.exit(1)
    click.echo("✔ all thresholds passed")


@cli.command("report")
@click.argument("run_path", type=click.Path(exists=True))
@click.option("-o", "--output", default="report.html", show_default=True)
def report_cmd(run_path: str, output: str):
    """Render a Markdown or HTML report from a run JSON."""
    from .report import render

    out = render(run_path, output)
    click.echo(f"✔ report written to {out}")


if __name__ == "__main__":
    cli()
