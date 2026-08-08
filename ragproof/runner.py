"""Run a dataset against a RAG adapter and score every sample."""

from __future__ import annotations

import datetime
import json
import os
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import __version__
from . import dataset as ds
from .adapters import build_adapter
from .config import RunConfig
from .metrics import (
    average_precision_at_k,
    citation_coverage,
    citation_matches,
    citation_precision,
    citation_recall,
    citation_validity,
    context_utilization,
    duplicate_rate,
    exact_match,
    hit_rate,
    is_empty_answer,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    refusal_rate,
    semantic_similarity,
)
from .metrics.judge import Judge, JudgeResult
from .provenance import sha256_file, sha256_json, sha256_values


def _git_sha() -> str | None:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _judge_detail(result: JudgeResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "score": result.score,
        "reason": result.reason,
        "cached": result.cached,
        "model": result.model,
        "votes": result.votes,
        "tokens": result.tokens,
        "estimated_cost": result.estimated_cost,
    }


def _evaluate_sample(sample: ds.Sample, adapter, judge: Judge | None, top_ks: list[int]) -> dict[str, Any]:
    response = adapter.ask(sample.question)
    metrics: dict[str, float | None] = {}
    judge_details: dict[str, Any] = {}
    if response.error is None:
        for k in top_ks:
            metrics[f"recall@{k}"] = recall_at_k(response.context_ids, sample.relevant_doc_ids, k)
            metrics[f"precision@{k}"] = precision_at_k(response.context_ids, sample.relevant_doc_ids, k)
            metrics[f"ndcg@{k}"] = ndcg_at_k(response.context_ids, sample.relevant_doc_ids, k)
            metrics[f"map@{k}"] = average_precision_at_k(response.context_ids, sample.relevant_doc_ids, k)
            metrics[f"hit_rate@{k}"] = hit_rate(response.context_ids, sample.relevant_doc_ids, k)
        metrics["mrr"] = mrr(response.context_ids, sample.relevant_doc_ids)
        metrics["duplicate_rate"] = duplicate_rate(response.context_ids)
        metrics["citation_coverage"] = citation_coverage(response.citations, response.contexts)
        metrics["citation_validity"] = citation_validity(response.citations, response.context_ids)
        metrics["citation_precision"] = citation_precision(response.citations, response.context_ids)
        metrics["citation_recall"] = citation_recall(response.citations, sample.expected_citations)
        metrics["exact_match"] = exact_match(response.answer, sample.ground_truths)
        metrics["semantic_similarity"] = semantic_similarity(response.answer, sample.ground_truths)
        metrics["empty_answer_rate"] = is_empty_answer(response.answer)
        metrics["refusal_rate"] = refusal_rate(response.answer, sample.answerable)
        metrics["context_utilization"] = context_utilization(response.answer, response.contexts)
        if sample.negative_doc_ids:
            negative = set(sample.negative_doc_ids)
            metrics["negative_hit_rate"] = 1.0 if negative.intersection(response.context_ids) else 0.0
        if judge:
            faithfulness = judge.evaluate_faithfulness(response.answer, response.contexts)
            groundedness = judge.evaluate_groundedness(response.answer, response.contexts)
            context_relevance = judge.evaluate_context_relevance(sample.question, response.contexts)
            relevancy = judge.evaluate_answer_relevancy(
                sample.question, response.answer, sample.ground_truth or ""
            )
            for name, result in {
                "faithfulness": faithfulness,
                "groundedness": groundedness,
                "context_relevance": context_relevance,
                "answer_relevancy": relevancy,
            }.items():
                metrics[name] = result.score if result else None
                judge_details[name] = _judge_detail(result)
            metrics["hallucination_rate"] = 1.0 - faithfulness.score if faithfulness else None
    return {
        "id": sample.id,
        "question": sample.question,
        "answer": response.answer,
        "contexts": response.contexts,
        "context_ids": response.context_ids,
        "retrieved_doc_ids": response.context_ids,
        "citations": response.citations,
        "expected_citations": sample.expected_citations,
        "tags": sample.tags,
        "difficulty": sample.difficulty,
        "answerable": sample.answerable,
        "latency_ms": response.latency_ms,
        "first_token_latency_ms": response.first_token_latency_ms,
        "output_char_count": response.output_char_count,
        "streamed": response.streamed,
        "error": response.error,
        "error_type": response.error_type,
        "metrics": metrics,
        "judge": judge_details,
        "citation_matches": citation_matches(response.citations, response.context_ids),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


def _aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    sums: dict[str, list[float]] = {}
    for result in results:
        for name, value in result["metrics"].items():
            if value is not None:
                sums.setdefault(name, []).append(float(value))
    aggregate = {name: sum(values) / len(values) for name, values in sums.items()}
    latencies = [float(r["latency_ms"]) for r in results if r["error"] is None]
    if latencies:
        aggregate["avg_latency_ms"] = sum(latencies) / len(latencies)
        aggregate["p50_latency_ms"] = _percentile(latencies, 50) or 0.0
        aggregate["p95_latency_ms"] = _percentile(latencies, 95) or 0.0
    first_token_latencies = [
        float(r["first_token_latency_ms"])
        for r in results
        if r.get("first_token_latency_ms") is not None and r["error"] is None
    ]
    if first_token_latencies:
        aggregate["avg_first_token_latency_ms"] = sum(first_token_latencies) / len(first_token_latencies)
        aggregate["p95_first_token_latency_ms"] = _percentile(first_token_latencies, 95) or 0.0
    successful = [r for r in results if r["error"] is None]
    if successful:
        aggregate["stream_rate"] = sum(1 for r in successful if r.get("streamed")) / len(successful)
    aggregate["error_rate"] = sum(1 for r in results if r["error"]) / len(results) if results else 0.0
    return aggregate


def _coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)

    def field_rate(predicate) -> dict[str, float | int]:
        available = sum(1 for result in results if predicate(result))
        return {"available": available, "total": total, "rate": available / total if total else 0.0}

    metric_names = sorted({name for result in results for name in result.get("metrics", {})})
    metric_coverage = {
        name: field_rate(lambda result, metric=name: result.get("metrics", {}).get(metric) is not None)
        for name in metric_names
    }
    return {
        "fields": {
            "successful_requests": field_rate(lambda result: result.get("error") is None),
            "answers": field_rate(lambda result: bool(str(result.get("answer", "")).strip())),
            "contexts": field_rate(lambda result: bool(result.get("contexts"))),
            "context_ids": field_rate(lambda result: bool(result.get("context_ids"))),
            "citations": field_rate(lambda result: bool(result.get("citations"))),
        },
        "metrics": metric_coverage,
    }


def _group_aggregates(results: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {"tags": {}, "difficulty": {}}
    for result in results:
        for tag in result.get("tags", []):
            groups["tags"].setdefault(tag, []).append(result)  # type: ignore[arg-type]
        difficulty = result.get("difficulty", "unspecified")
        groups["difficulty"].setdefault(difficulty, []).append(result)  # type: ignore[arg-type]
    return {
        dimension: {name: _aggregate(items) for name, items in values.items()}
        for dimension, values in groups.items()
    }


def run(config: RunConfig, output: str | Path) -> dict[str, Any]:
    started = time.perf_counter()
    samples = ds.load(config.dataset)
    samples = ds.filter_samples(
        samples,
        limit=config.sample_limit,
        include_tags=set(config.include_tags),
        exclude_tags=set(config.exclude_tags),
    )
    if config.seed is not None:
        samples = list(samples)
        random.Random(config.seed).shuffle(samples)
    if not samples:
        raise ValueError("no samples selected; check dataset filters and sample_limit")
    adapter = build_adapter(config.adapter, retries=config.retries, retry_backoff=config.retry_backoff)
    judge = Judge(config.judge) if config.judge.enabled else None
    top_ks = config.effective_top_ks()

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        results = list(pool.map(lambda sample: _evaluate_sample(sample, adapter, judge, top_ks), samples))

    total_cost = sum(
        detail.get("estimated_cost", 0.0)
        for result in results
        for detail in result.get("judge", {}).values()
        if detail
    )
    coverage = _coverage(results)
    report = {
        "name": config.name,
        "ragproof_version": __version__,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "duration_ms": (time.perf_counter() - started) * 1000,
        "git_sha": config.git_sha or _git_sha(),
        "dataset": str(config.dataset),
        "dataset_sample_count": ds.samples_count(config.dataset),
        "sample_count": len(samples),
        "provenance": {
            "schema_version": 1,
            "dataset_sha256": sha256_file(config.dataset),
            "config_sha256": sha256_json(config.summary()),
            "selected_sample_ids_sha256": sha256_values(sample.id for sample in samples),
        },
        "top_ks": top_ks,
        "config_summary": config.summary(),
        "aggregate": _aggregate(results),
        "groups": _group_aggregates(results),
        "coverage": coverage,
        "cost": {"estimated_total": total_cost},
        "results": results,
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    required = sorted(set(config.required_metrics))
    missing = [
        metric
        for metric in required
        if coverage["metrics"].get(metric, {}).get("rate", 0.0) < 1.0
    ]
    if missing:
        raise ValueError(
            "required metrics are unavailable for every selected sample: "
            + ", ".join(missing)
            + f"; inspect coverage in {out}"
        )
    return report
