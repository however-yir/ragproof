"""Run a dataset against a RAG adapter and score every sample."""

from __future__ import annotations

import datetime
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import dataset as ds
from .adapters import build_adapter
from .config import RunConfig
from .metrics import (
    citation_coverage,
    citation_validity,
    hit_rate,
    mrr,
    precision_at_k,
    recall_at_k,
)
from .metrics.judge import Judge


def _evaluate_sample(sample: ds.Sample, adapter, judge: Judge | None, k: int) -> dict[str, Any]:
    resp = adapter.ask(sample.question)
    metrics: dict[str, float | None] = {}
    if resp.error is None:
        metrics[f"recall@{k}"] = recall_at_k(resp.context_ids, sample.relevant_doc_ids, k)
        metrics[f"precision@{k}"] = precision_at_k(resp.context_ids, sample.relevant_doc_ids, k)
        metrics["mrr"] = mrr(resp.context_ids, sample.relevant_doc_ids)
        metrics[f"hit_rate@{k}"] = hit_rate(resp.context_ids, sample.relevant_doc_ids, k)
        metrics["citation_coverage"] = citation_coverage(resp.citations, resp.contexts)
        metrics["citation_validity"] = citation_validity(resp.citations, resp.context_ids)
        if judge:
            metrics["faithfulness"] = judge.faithfulness(resp.answer, resp.contexts)
            metrics["answer_relevancy"] = judge.answer_relevancy(
                sample.question, resp.answer, sample.ground_truth
            )
    return {
        "id": sample.id,
        "question": sample.question,
        "answer": resp.answer,
        "citations": resp.citations,
        "latency_ms": resp.latency_ms,
        "error": resp.error,
        "metrics": metrics,
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    sums: dict[str, list[float]] = {}
    for r in results:
        for name, value in r["metrics"].items():
            if value is not None:
                sums.setdefault(name, []).append(value)
    agg = {name: sum(vals) / len(vals) for name, vals in sums.items()}
    latencies = [r["latency_ms"] for r in results if r["error"] is None]
    if latencies:
        agg["avg_latency_ms"] = sum(latencies) / len(latencies)
    agg["error_rate"] = sum(1 for r in results if r["error"]) / len(results) if results else 0.0
    return agg


def run(config: RunConfig, output: str | Path) -> dict[str, Any]:
    samples = ds.load(config.dataset)
    adapter = build_adapter(config.adapter)
    judge = Judge(config.judge) if config.judge.enabled else None

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        results = list(
            pool.map(lambda s: _evaluate_sample(s, adapter, judge, config.top_k), samples)
        )

    report = {
        "name": config.name,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dataset": str(config.dataset),
        "sample_count": len(samples),
        "aggregate": _aggregate(results),
        "results": results,
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
