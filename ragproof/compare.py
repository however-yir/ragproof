"""Baseline/current comparison and CI regression gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class ThresholdResult:
    metric: str
    threshold: float
    current: float | None
    baseline: float | None
    passed: bool
    reason: str
    kind: str = "absolute"
    actual: float | None = None


def parse_thresholds(specs: list[str]) -> dict[str, float]:
    """Parse ``metric=0.8`` or ``metric>=0.8`` absolute gates."""
    out: dict[str, float] = {}
    for spec in specs:
        if ">=" in spec:
            name, val = spec.split(">=", 1)
        elif "=" in spec:
            name, val = spec.split("=", 1)
        else:
            raise ValueError(f"invalid threshold spec (expected name=value): {spec!r}")
        name = name.strip()
        if not name:
            raise ValueError(f"metric name is empty: {spec!r}")
        out[name] = float(val.strip())
    return out


def parse_relative_drops(specs: Iterable[str]) -> dict[str, float]:
    """Parse ``metric=5%`` or ``metric=0.05`` maximum relative drops."""
    out: dict[str, float] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"invalid relative-drop spec: {spec!r}")
        name, raw = spec.split("=", 1)
        raw = raw.strip()
        value = float(raw.removesuffix("%"))
        if raw.endswith("%"):
            value /= 100
        if value < 0:
            raise ValueError("relative drop must be non-negative")
        out[name.strip()] = value
    return out


def _one_absolute(metric: str, threshold: float, baseline: dict[str, float], current: dict[str, float]) -> ThresholdResult:
    cur_val = current.get(metric)
    base_val = baseline.get(metric)
    if cur_val is None:
        return ThresholdResult(metric, threshold, cur_val, base_val, False, f"metric '{metric}' missing from current run")
    passed = cur_val >= threshold
    reason = f"{cur_val:.3f} >= threshold {threshold:.3f}" if passed else f"{cur_val:.3f} < threshold {threshold:.3f}"
    return ThresholdResult(metric, threshold, cur_val, base_val, passed, reason, actual=cur_val)


def compare(
    baseline_path: str | Path,
    current_path: str | Path,
    thresholds: dict[str, float],
    *,
    min_deltas: dict[str, float] | None = None,
    max_relative_drops: dict[str, float] | None = None,
) -> tuple[list[ThresholdResult], bool]:
    """Return results for absolute, minimum-delta, and relative-drop gates."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))
    b_agg: dict[str, float] = baseline.get("aggregate", {})
    c_agg: dict[str, float] = current.get("aggregate", {})
    results = [_one_absolute(metric, threshold, b_agg, c_agg) for metric, threshold in thresholds.items()]

    for metric, minimum_delta in (min_deltas or {}).items():
        cur_val = c_agg.get(metric)
        base_val = b_agg.get(metric)
        delta = cur_val - base_val if cur_val is not None and base_val is not None else None
        passed = delta is not None and delta >= minimum_delta
        reason = (
            f"delta {delta:+.3f} >= minimum {minimum_delta:+.3f}"
            if passed
            else f"delta {delta:+.3f} < minimum {minimum_delta:+.3f}"
            if delta is not None
            else f"metric '{metric}' missing from baseline or current run"
        )
        results.append(ThresholdResult(metric, minimum_delta, cur_val, base_val, passed, reason, "delta", delta))

    for metric, max_drop in (max_relative_drops or {}).items():
        cur_val = c_agg.get(metric)
        base_val = b_agg.get(metric)
        if cur_val is None or base_val is None:
            drop = None
            passed = False
            reason = f"metric '{metric}' missing from baseline or current run"
        elif base_val == 0:
            drop = 0.0 if cur_val >= 0 else 1.0
            passed = drop <= max_drop
            reason = f"relative drop {drop:.1%} {'<=' if passed else '>'} allowed {max_drop:.1%}"
        else:
            drop = (base_val - cur_val) / abs(base_val)
            passed = drop <= max_drop
            reason = f"relative drop {drop:.1%} {'<=' if passed else '>'} allowed {max_drop:.1%}"
        results.append(ThresholdResult(metric, max_drop, cur_val, base_val, passed, reason, "relative_drop", drop))
    return results, all(result.passed for result in results)


def recommend_thresholds(run_path: str | Path, *, floor: float = 0.95) -> dict[str, float]:
    """Suggest absolute gates at ``floor`` of each bounded baseline metric."""
    data = json.loads(Path(run_path).read_text(encoding="utf-8"))
    return {
        name: round(value * floor, 4)
        for name, value in data.get("aggregate", {}).items()
        if 0 <= value <= 1
    }


def results_as_dicts(results: list[ThresholdResult]) -> list[dict[str, object]]:
    return [asdict(result) for result in results]
