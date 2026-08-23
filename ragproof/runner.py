"""Run a dataset against a RAG adapter and score every sample."""

from __future__ import annotations

import datetime
import json
import os
import random
import shutil
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from itertools import islice
from pathlib import Path
from typing import Any

from . import __version__
from . import dataset as ds
from .adapters import build_adapter
from .config import IdNormalizationConfig, RunConfig
from .io import atomic_text_writer, atomic_write_text
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
    lexical_token_f1,
    mrr,
    ndcg_at_k,
    precision_at_k,
    rank_sensitivity,
    recall_at_k,
    refusal_rate,
    token_count,
    tokens_per_second,
    unanswerable_correctness,
)
from .metrics.embedding import embedding_similarity
from .metrics.judge import Judge, JudgeResult
from .normalization import normalize_ids, normalize_relevance
from .privacy import redact_nested
from .provenance import sha256_file, sha256_json, sha256_values
from .schema import CURRENT_RUN_SCHEMA_VERSION


def _git_sha() -> str | None:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    git = shutil.which("git")
    if not git:
        return None
    try:
        return subprocess.run(  # noqa: S603 - resolved git binary with fixed arguments
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
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
    id_normalization: IdNormalizationConfig | None = None,
    refusal_patterns: list[str] | None = None,
    refusal_exceptions: list[str] | None = None,
    refusal_language: str = "auto",
) -> dict[str, Any]:
    response = adapter.ask(sample.question)
    normalization = id_normalization or IdNormalizationConfig()
    context_ids = normalize_ids(response.context_ids, normalization)
    citations = normalize_ids(response.citations, normalization)
    qrels = normalize_relevance(sample.relevance_scores, normalization)
    expected_citations = normalize_ids(sample.expected_citations, normalization)
    metrics: dict[str, float | None] = {}
    judge_details: dict[str, Any] = {}
    if response.error is None:
        for k in top_ks:
            metrics[f"recall@{k}"] = recall_at_k(context_ids, qrels, k)
            metrics[f"precision@{k}"] = precision_at_k(context_ids, qrels, k)
            metrics[f"ndcg@{k}"] = ndcg_at_k(context_ids, qrels, k)
            metrics[f"map@{k}"] = average_precision_at_k(context_ids, qrels, k)
            metrics[f"hit_rate@{k}"] = hit_rate(context_ids, qrels, k)
            metrics[f"rank_sensitivity@{k}"] = rank_sensitivity(context_ids, qrels, k)
        metrics["mrr"] = mrr(context_ids, qrels)
        metrics["duplicate_rate"] = duplicate_rate(context_ids)
        metrics["citation_coverage"] = citation_coverage(response.citations, response.contexts)
        metrics["citation_validity"] = citation_validity(citations, context_ids)
        metrics["citation_precision"] = citation_precision(citations, context_ids)
        metrics["citation_recall"] = citation_recall(citations, expected_citations)
        metrics["citation_span_overlap"] = citation_span_overlap(
            response.answer,
            citations,
            response.contexts,
            context_ids,
        )
        metrics["exact_match"] = exact_match(response.answer, sample.ground_truths)
        lexical_score = lexical_token_f1(response.answer, sample.ground_truths)
        metrics["lexical_token_f1"] = lexical_score
        metrics["semantic_similarity"] = lexical_score
        if embedding_model:
            metrics["embedding_similarity"] = embedding_similarity(response.answer, sample.ground_truths, embedding_model)
        metrics["empty_answer_rate"] = is_empty_answer(response.answer)
        metrics["refusal_rate"] = refusal_rate(
            response.answer,
            sample.answerable,
            patterns=refusal_patterns,
            exceptions=refusal_exceptions,
            language=refusal_language,
        )
        metrics["unanswerable_correctness"] = unanswerable_correctness(
            response.answer,
            sample.answerable,
            patterns=refusal_patterns,
            exceptions=refusal_exceptions,
            language=refusal_language,
        )
        metrics["context_utilization"] = context_utilization(response.answer, response.contexts)
        metrics["context_redundancy"] = context_redundancy(response.contexts)
        metrics["context_diversity"] = context_diversity(response.contexts)
        metrics["claim_support"] = claim_support(response.answer, response.contexts)
        metrics["output_token_count"] = float(token_count(response.answer, tokenizer=tokenizer))
        metrics["tokens_per_second"] = tokens_per_second(response.answer, response.latency_ms, tokenizer=tokenizer)
        if sample.negative_doc_ids:
            negative = set(normalize_ids(sample.negative_doc_ids, normalization))
            metrics["negative_hit_rate"] = 1.0 if negative.intersection(context_ids) else 0.0
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
        "context_ids": context_ids,
        "retrieved_doc_ids": context_ids,
        "citations": citations,
        "expected_citations": expected_citations,
        "relevance_scores": qrels,
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
        "citation_matches": citation_matches(citations, context_ids),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


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


class _OnlineAggregate:
    """Retain only aggregate state while sample details stream to JSONL."""

    def __init__(self, dimensions: list[str] | None = None):
        self.total = 0
        self.successful = 0
        self.streamed = 0
        self.metric_sums: dict[str, float] = {}
        self.metric_counts: dict[str, int] = {}
        self.metric_names: set[str] = set()
        self.latencies: list[float] = []
        self.first_token_latencies: list[float] = []
        self.field_counts = {
            "successful_requests": 0,
            "answers": 0,
            "contexts": 0,
            "context_ids": 0,
            "citations": 0,
        }
        self.dimensions = dimensions or []
        self.groups: dict[str, dict[str, _OnlineAggregate]] = {
            dimension: {} for dimension in self.dimensions
        }

    def add(self, result: dict[str, Any]) -> None:
        self.total += 1
        successful = result.get("error") is None
        if successful:
            self.successful += 1
            self.field_counts["successful_requests"] += 1
            self.latencies.append(float(result.get("latency_ms", 0.0)))
            if result.get("first_token_latency_ms") is not None:
                self.first_token_latencies.append(float(result["first_token_latency_ms"]))
            if result.get("streamed"):
                self.streamed += 1
        for field in ("answers", "contexts", "context_ids", "citations"):
            source = "answer" if field == "answers" else field
            if result.get(source):
                self.field_counts[field] += 1
        for name, value in result.get("metrics", {}).items():
            self.metric_names.add(name)
            if value is not None:
                self.metric_sums[name] = self.metric_sums.get(name, 0.0) + float(value)
                self.metric_counts[name] = self.metric_counts.get(name, 0) + 1
        for dimension in self.dimensions:
            for value in _dimension_values(result, dimension):
                self.groups[dimension].setdefault(value, _OnlineAggregate()).add(result)

    def aggregate(self) -> dict[str, float]:
        aggregate = {
            name: self.metric_sums[name] / self.metric_counts[name]
            for name in sorted(self.metric_sums)
        }
        if self.latencies:
            aggregate["avg_latency_ms"] = sum(self.latencies) / len(self.latencies)
            aggregate["p50_latency_ms"] = _percentile(self.latencies, 50) or 0.0
            aggregate["p95_latency_ms"] = _percentile(self.latencies, 95) or 0.0
        if self.first_token_latencies:
            aggregate["avg_first_token_latency_ms"] = sum(self.first_token_latencies) / len(
                self.first_token_latencies
            )
            aggregate["p95_first_token_latency_ms"] = (
                _percentile(self.first_token_latencies, 95) or 0.0
            )
        if self.successful:
            aggregate["stream_rate"] = self.streamed / self.successful
        aggregate["error_rate"] = (
            (self.total - self.successful) / self.total if self.total else 0.0
        )
        return aggregate

    def coverage(self) -> dict[str, Any]:
        def entry(available: int) -> dict[str, float | int]:
            return {
                "available": available,
                "total": self.total,
                "rate": available / self.total if self.total else 0.0,
            }

        return {
            "fields": {name: entry(count) for name, count in self.field_counts.items()},
            "metrics": {
                name: entry(self.metric_counts.get(name, 0)) for name in sorted(self.metric_names)
            },
        }

    def group_aggregates(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            dimension: {
                value: aggregate.aggregate() for value, aggregate in sorted(groups.items())
            }
            for dimension, groups in self.groups.items()
        }


def _iter_selected_samples(config: RunConfig) -> Iterator[ds.Sample]:
    """Stream simple filters; materialize only when shuffling or stratifying is requested."""
    if config.stratify_by or config.seed is not None:
        samples = ds.filter_samples(
            ds.load(config.dataset, reject_duplicates=config.deduplicate_questions),
            limit=config.sample_limit,
            include_tags=set(config.include_tags),
            exclude_tags=set(config.exclude_tags),
            stratify_by=config.stratify_by,
            seed=config.seed,
        )
        if config.seed is not None:
            random.Random(config.seed).shuffle(samples)  # noqa: S311 - reproducible evaluation ordering
        yield from samples
        return

    emitted = 0
    include_tags = set(config.include_tags)
    exclude_tags = set(config.exclude_tags)
    for sample in ds.iter_load(
        config.dataset,
        reject_duplicates=config.deduplicate_questions,
    ):
        if include_tags and not include_tags.intersection(sample.tags):
            continue
        if exclude_tags.intersection(sample.tags):
            continue
        yield sample
        emitted += 1
        if config.sample_limit is not None and emitted >= config.sample_limit:
            return


def _batches(samples: Iterator[ds.Sample], size: int) -> Iterator[list[ds.Sample]]:
    while batch := list(islice(samples, size)):
        yield batch


def run(config: RunConfig, output: str | Path) -> dict[str, Any]:
    started = time.perf_counter()
    out = Path(output)
    use_result_sink = config.stream_results or config.result_sink is not None
    sink_path: Path | None = None
    if use_result_sink:
        sink_path = Path(config.result_sink) if config.result_sink else out.with_suffix(".results.jsonl")
        if not sink_path.is_absolute():
            sink_path = out.parent / sink_path
    adapter = build_adapter(config.adapter, retries=config.retries, retry_backoff=config.retry_backoff)
    judge = Judge(config.judge) if config.judge.enabled else None
    top_ks = config.effective_top_ks()
    accumulator = _OnlineAggregate(config.group_by)
    results: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    total_cost = 0.0
    sink_context = atomic_text_writer(sink_path) if sink_path else nullcontext(None)

    try:
        with sink_context as sink, ThreadPoolExecutor(max_workers=config.concurrency) as pool:
            for batch in _batches(_iter_selected_samples(config), config.batch_size):
                evaluated = pool.map(
                    lambda sample: _evaluate_sample(
                        sample,
                        adapter,
                        judge,
                        top_ks,
                        tokenizer=config.tokenizer,
                        embedding_model=config.embedding_model,
                        id_normalization=config.id_normalization,
                        refusal_patterns=config.refusal_patterns,
                        refusal_exceptions=config.refusal_exceptions,
                        refusal_language=config.refusal_language,
                    ),
                    batch,
                )
                for sample, result in zip(batch, evaluated, strict=True):
                    selected_ids.append(sample.id)
                    accumulator.add(result)
                    total_cost += sum(
                        detail.get("estimated_cost", 0.0)
                        for detail in result.get("judge", {}).values()
                        if detail
                    )
                    if sink is not None:
                        persisted = redact_nested(result) if config.redact_sensitive else result
                        sink.write(json.dumps(persisted, ensure_ascii=False) + "\n")
                    else:
                        results.append(result)
            if not accumulator.total:
                raise ValueError("no samples selected; check dataset filters and sample_limit")
    finally:
        close_adapter = getattr(adapter, "close", None)
        if callable(close_adapter):
            close_adapter()
        if judge:
            judge.close()

    coverage = accumulator.coverage()
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
        "sample_count": accumulator.total,
        "provenance": {
            "schema_version": 2,
            "dataset_sha256": sha256_file(config.dataset),
            "config_sha256": sha256_json(config.fingerprint_summary()),
            "config_fingerprint_version": 2,
            "legacy_config_sha256": sha256_json(config.legacy_fingerprint_summary()),
            "selected_sample_ids_sha256": sha256_values(selected_ids),
            "dataset_manifest": dataset_manifest,
            "judge_prompt_version": config.judge.prompt_version,
            "judge_prompt_sha256": judge.prompt_fingerprint if judge else None,
            "adapter_type": config.adapter.type,
            "group_by": config.group_by,
        },
        "top_ks": top_ks,
        "config_summary": config_summary,
        "aggregate": accumulator.aggregate(),
        "groups": accumulator.group_aggregates(),
        "coverage": coverage,
        "cost": {"estimated_total": total_cost},
        "judge_status": {
            "failures": judge.failures if judge else 0,
            "circuit_open": judge.circuit_open if judge else False,
        },
        "deprecations": {
            "semantic_similarity": "Use lexical_token_f1; semantic_similarity remains a compatibility alias for one release cycle."
        },
        "results_jsonl": sink_path.name if sink_path else None,
        "results": results,
    }
    if config.redact_sensitive:
        report = redact_nested(report)
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
    if config.min_sample_count is not None and accumulator.total < config.min_sample_count:
        raise ValueError(
            f"selected sample count {accumulator.total} is below min_sample_count {config.min_sample_count}"
        )
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
