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
    citation_span_overlap,
    citation_validity,
    claim_support,
    context_diversity,
    context_redundancy,
    context_utilization,
    duplicate_rate,
    exact_match,
    hit_rate,
    is_empty_answer,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    rank_sensitivity,
    refusal_rate,
    semantic_similarity,
    token_count,
    tokens_per_second,
    unanswerable_correctness,
)
from .metrics.judge import Judge, JudgeResult
from .metrics.embedding import embedding_similarity
from .io import atomic_write_text
from .privacy import redact_nested
from .provenance import sha256_file, sha256_json, sha256_values
from .schema import CURRENT_RUN_SCHEMA_VERSION


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


def _evaluate_sample(
    sample: ds.Sample,
    adapter,
    judge: Judge | None,
    top_ks: list[int],
    *,
    tokenizer: str = "heuristic",
    embedding_model: str | None = None,
) -> dict[str, Any]:
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
            metrics[f"rank_sensitivity@{k}"] = rank_sensitivity(response.context_ids, sample.relevant_doc_ids, k)
        metrics["mrr"] = mrr(response.context_ids, sample.relevant_doc_ids)
        metrics["duplicate_rate"] = duplicate_rate(response.context_ids)
        metrics["citation_coverage"] = citation_coverage(response.citations, response.contexts)
        metrics["citation_validity"] = citation_validity(response.citations, response.context_ids)
        metrics["citation_precision"] = citation_precision(response.citations, response.context_ids)
        metrics["citation_recall"] = citation_recall(response.citations, sample.expected_citations)
        metrics["citation_span_overlap"] = citation_span_overlap(
            response.answer,
            response.citations,
            response.contexts,
            response.context_ids,
        )
        metrics["exact_match"] = exact_match(response.answer, sample.ground_truths)
        metrics["semantic_similarity"] = semantic_similarity(response.answer, sample.ground_truths)
        if embedding_model:
            metrics["embedding_similarity"] = embedding_similarity(response.answer, sample.ground_truths, embedding_model)
        metrics["empty_answer_rate"] = is_empty_answer(response.answer)
        metrics["refusal_rate"] = refusal_rate(response.answer, sample.answerable)
        metrics["unanswerable_correctness"] = unanswerable_correctness(response.answer, sample.answerable)
        metrics["context_utilization"] = context_utilization(response.answer, response.contexts)
        metrics["context_redundancy"] = context_redundancy(response.contexts)
        metrics["context_diversity"] = context_diversity(response.contexts)
        metrics["claim_support"] = claim_support(response.answer, response.contexts)
        metrics["output_token_count"] = float(token_count(response.answer, tokenizer=tokenizer))
        metrics["tokens_per_second"] = tokens_per_second(response.answer, response.latency_ms, tokenizer=tokenizer)
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
            votes = [vote for detail in judge_details.values() for vote in (detail.get("votes") or [])]
            if votes:
                metrics["judge_agreement"] = max(0.0, 1.0 - (max(votes) - min(votes)))
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
        "metadata": sample.metadata,
        "latency_ms": response.latency_ms,
        "first_token_latency_ms": response.first_token_latency_ms,
        "output_char_count": response.output_char_count,
        "output_token_count": token_count(response.answer, tokenizer=tokenizer),
        "tokens_per_second": tokens_per_second(response.answer, response.latency_ms, tokenizer=tokenizer),
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


def _dimension_values(result: dict[str, Any], dimension: str) -> list[str]:
    if dimension == "tags":
        return [str(value) for value in result.get("tags", [])] or ["untagged"]
    if dimension == "answerable":
        return [str(bool(result.get("answerable"))).lower()]
    if dimension.startswith("metadata."):
        key = dimension.split(".", 1)[1]
        value = (result.get("metadata") or {}).get(key, "missing")
        return [str(value)]
    return [str(result.get(dimension, "missing"))]


def _group_aggregates(results: list[dict[str, Any]], dimensions: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {dimension: {} for dimension in dimensions}
    for result in results:
        for dimension in dimensions:
            for value in _dimension_values(result, dimension):
                groups[dimension].setdefault(value, []).append(result)  # type: ignore[arg-type]
    return {
        dimension: {name: _aggregate(items) for name, items in values.items()}
        for dimension, values in groups.items()
    }


def run(config: RunConfig, output: str | Path) -> dict[str, Any]:
    started = time.perf_counter()
    samples = ds.load(config.dataset, reject_duplicates=config.deduplicate_questions)
    samples = ds.filter_samples(
        samples,
        limit=config.sample_limit,
        include_tags=set(config.include_tags),
        exclude_tags=set(config.exclude_tags),
        stratify_by=config.stratify_by,
        seed=config.seed,
    )
    if config.seed is not None:
        samples = list(samples)
        random.Random(config.seed).shuffle(samples)
    if not samples:
        raise ValueError("no samples selected; check dataset filters and sample_limit")
    adapter = build_adapter(config.adapter, retries=config.retries, retry_backoff=config.retry_backoff)
    judge = Judge(config.judge) if config.judge.enabled else None
    top_ks = config.effective_top_ks()

    try:
        with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
            results = list(
                pool.map(
                    lambda sample: _evaluate_sample(
                        sample,
                        adapter,
                        judge,
                        top_ks,
                        tokenizer=config.tokenizer,
                        embedding_model=config.embedding_model,
                    ),
                    samples,
                )
            )
    finally:
        close_adapter = getattr(adapter, "close", None)
        if callable(close_adapter):
            close_adapter()
        if judge:
            judge.close()

    total_cost = sum(
        detail.get("estimated_cost", 0.0)
        for result in results
        for detail in result.get("judge", {}).values()
        if detail
    )
    coverage = _coverage(results)
    config_summary = config.summary()
    dataset_label = str(config_summary["dataset"])
    dataset_manifest = ds.manifest(config.dataset)
    dataset_manifest["path"] = dataset_label
    report: dict[str, Any] = {
        "schema_version": CURRENT_RUN_SCHEMA_VERSION,
        "name": config.name,
        "ragproof_version": __version__,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "duration_ms": (time.perf_counter() - started) * 1000,
        "git_sha": config.git_sha or _git_sha(),
        "dataset": dataset_label,
        "dataset_sample_count": ds.samples_count(config.dataset),
        "sample_count": len(samples),
        "provenance": {
            "schema_version": 2,
            "dataset_sha256": sha256_file(config.dataset),
            "config_sha256": sha256_json(config.fingerprint_summary()),
            "config_fingerprint_version": 2,
            "legacy_config_sha256": sha256_json(config.legacy_fingerprint_summary()),
            "selected_sample_ids_sha256": sha256_values(sample.id for sample in samples),
            "dataset_manifest": dataset_manifest,
            "judge_prompt_version": config.judge.prompt_version,
            "judge_prompt_sha256": judge.prompt_fingerprint if judge else None,
            "adapter_type": config.adapter.type,
            "group_by": config.group_by,
        },
        "top_ks": top_ks,
        "config_summary": config_summary,
        "aggregate": _aggregate(results),
        "groups": _group_aggregates(results, config.group_by),
        "coverage": coverage,
        "cost": {"estimated_total": total_cost},
        "judge_status": {
            "failures": judge.failures if judge else 0,
            "circuit_open": judge.circuit_open if judge else False,
        },
        "results": results,
    }
    if config.redact_sensitive:
        report = redact_nested(report)
    out = Path(output)
    atomic_write_text(out, json.dumps(report, ensure_ascii=False, indent=2))
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
    if config.min_sample_count is not None and len(samples) < config.min_sample_count:
        raise ValueError(f"selected sample count {len(samples)} is below min_sample_count {config.min_sample_count}")
    required_fields = sorted(set(config.required_fields))
    missing_fields = [
        field
        for field in required_fields
        if coverage["fields"].get(field, {}).get("rate", 0.0) < 1.0
    ]
    if missing_fields:
        raise ValueError(
            "required fields are unavailable for every selected sample: "
            + ", ".join(missing_fields)
            + f"; inspect coverage in {out}"
        )
    coverage_failures = [
        f"{field}<{minimum:.1%}"
        for field, minimum in config.min_coverage.items()
        if coverage["metrics"].get(field, coverage["fields"].get(field, {})).get("rate", 0.0) < minimum
    ]
    if coverage_failures:
        raise ValueError("coverage gates failed: " + ", ".join(coverage_failures))
    return report
