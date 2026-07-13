"""Regression comparison: baseline vs current run.

Parses threshold specs like "faithfulness=0.8" or "recall@5=0.7",
compares aggregate metrics, and exits non-zero on failure so CI gates work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ThresholdResult:
    metric: str
    threshold: float
    current: float | None
    baseline: float | None
    passed: bool
    reason: str


def parse_thresholds(specs: list[str]) -> dict[str, float]:
    """Parse ["faithfulness=0.8", "recall@5=0.7"] into a dict."""
    out: dict[str, float] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"invalid threshold spec (expected name=value): {spec!r}")
        name, val = spec.split("=", 1)
        out[name.strip()] = float(val.strip())
    return out


def compare(
    baseline_path: str | Path,
    current_path: str | Path,
    thresholds: dict[str, float],
) -> tuple[list[ThresholdResult], bool]:
    """Return (results, all_passed)."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))
    b_agg: dict[str, float] = baseline.get("aggregate", {})
    c_agg: dict[str, float] = current.get("aggregate", {})

    results: list[ThresholdResult] = []
    for metric, threshold in thresholds.items():
        cur_val = c_agg.get(metric)
        base_val = b_agg.get(metric)
        if cur_val is None:
            passed = False
            reason = f"metric '{metric}' missing from current run"
        elif cur_val < threshold:
            passed = False
            reason = f"{cur_val:.3f} < threshold {threshold:.3f}"
        else:
            passed = True
            reason = f"{cur_val:.3f} >= threshold {threshold:.3f}"
        results.append(
            ThresholdResult(
                metric=metric,
                threshold=threshold,
                current=cur_val,
                baseline=base_val,
                passed=passed,
                reason=reason,
            )
        )
    return results, all(r.passed for r in results)
