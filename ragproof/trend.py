"""Multi-run trend summaries and lightweight bootstrap confidence intervals."""

from __future__ import annotations

import json
import random
import statistics
from pathlib import Path
from typing import Iterable


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_interval(values: Iterable[float], *, iterations: int = 1000, confidence: float = 0.95, seed: int = 42) -> tuple[float, float] | None:
    """Return a reproducible percentile bootstrap CI for a mean."""
    numbers = [float(value) for value in values]
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(numbers, k=len(numbers))) for _ in range(max(1, iterations))]
    alpha = (1 - confidence) / 2
    return _percentile(means, alpha), _percentile(means, 1 - alpha)


def summarize_runs(paths: Iterable[str | Path], metrics: Iterable[str] | None = None) -> dict:
    """Summarize aggregate metrics across run JSON files in chronological order."""
    runs = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        runs.append({"path": str(path), "timestamp": data.get("timestamp", ""), "git_sha": data.get("git_sha"), "aggregate": data.get("aggregate", {})})
    runs.sort(key=lambda item: (item["timestamp"], item["path"]))
    names = sorted(set(metrics or ()) or {name for run in runs for name in run["aggregate"]})
    summary = {}
    for name in names:
        values = [float(run["aggregate"][name]) for run in runs if run["aggregate"].get(name) is not None]
        interval = bootstrap_interval(values)
        summary[name] = {
            "count": len(values),
            "latest": values[-1] if values else None,
            "mean": statistics.fmean(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "ci95_low": interval[0] if interval else None,
            "ci95_high": interval[1] if interval else None,
            "values": values,
        }
    return {"run_count": len(runs), "runs": runs, "metrics": summary}


def find_first_regression(paths: Iterable[str | Path], metric: str, threshold: float, *, maximum: bool = False) -> str | None:
    """Find the first run that crosses a gate, useful for local regression bisects."""
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        value = data.get("aggregate", {}).get(metric)
        if value is None:
            continue
        failed = float(value) > threshold if maximum else float(value) < threshold
        if failed:
            return str(path)
    return None


def recommend_from_history(paths: Iterable[str | Path], *, floor: float = 0.95, headroom: float = 1.05) -> dict[str, dict[str, float]]:
    """Recommend gates from the recent lower/upper percentiles of run history."""
    summary = summarize_runs(paths)
    higher: dict[str, float] = {}
    maximum: dict[str, float] = {}
    lower_names = {"error_rate", "avg_latency_ms", "p95_latency_ms", "hallucination_rate", "duplicate_rate"}
    for name, item in summary["metrics"].items():
        latest = item.get("latest")
        if latest is None:
            continue
        if name in lower_names:
            maximum[name] = round(float(latest) * headroom, 4)
        elif 0 <= float(latest) <= 1:
            higher[name] = round(float(latest) * floor, 4)
    return {"thresholds": higher, "max_thresholds": maximum}
