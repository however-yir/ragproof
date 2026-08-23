"""Dataset loading, validation, filtering, and schema helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .privacy import redact_text as redact_text


class Sample(BaseModel):
    """One JSONL evaluation sample.

    The extra fields are intentionally data-oriented: tags and difficulty make
    it possible to find regressions in a slice of a dataset, while multiple
    references and expected citations cover real-world QA datasets.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    ground_truth: str = ""
    ground_truths: list[str] = Field(default_factory=list)
    relevant_doc_ids: list[str] = Field(default_factory=list)
    relevance_scores: dict[str, float] = Field(default_factory=dict)
    negative_doc_ids: list[str] = Field(default_factory=list)
    expected_citations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "unspecified"
    answerable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "question")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("id and question must not be empty")
        return value

    @model_validator(mode="after")
    def normalize_references(self) -> Sample:
        refs = list(dict.fromkeys([ref for ref in [self.ground_truth, *self.ground_truths] if ref]))
        self.ground_truths = refs
        if not self.ground_truth and refs:
            self.ground_truth = refs[0]
        self.tags = sorted(set(tag.strip() for tag in self.tags if tag.strip()))
        if any(score < 0 for score in self.relevance_scores.values()):
            raise ValueError("relevance_scores values must be non-negative")
        for doc_id in self.relevant_doc_ids:
            self.relevance_scores.setdefault(doc_id, 1.0)
        self.relevant_doc_ids = list(
            dict.fromkeys([*self.relevant_doc_ids, *(doc_id for doc_id, score in self.relevance_scores.items() if score > 0)])
        )
        return self


_LIST_FIELDS = {
    "ground_truths",
    "relevant_doc_ids",
    "negative_doc_ids",
    "expected_citations",
    "tags",
}


def _parse_list_cell(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("list-like cell must contain a JSON array")
        return [str(item) for item in parsed]
    separator = "|" if "|" in text else ";" if ";" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def _normalize_tabular_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {str(key): value for key, value in record.items() if key and value is not None and value != ""}
    for field in _LIST_FIELDS.intersection(normalized):
        normalized[field] = _parse_list_cell(normalized[field])
    if "metadata" in normalized and isinstance(normalized["metadata"], str):
        parsed = json.loads(normalized["metadata"])
        if not isinstance(parsed, dict):
            raise ValueError("metadata cell must contain a JSON object")
        normalized["metadata"] = parsed
    if "relevance_scores" in normalized and isinstance(normalized["relevance_scores"], str):
        parsed_scores = json.loads(normalized["relevance_scores"])
        if not isinstance(parsed_scores, dict):
            raise ValueError("relevance_scores cell must contain a JSON object")
        normalized["relevance_scores"] = parsed_scores
    if "answerable" in normalized and isinstance(normalized["answerable"], str):
        value = normalized["answerable"].strip().lower()
        if value in {"true", "1", "yes"}:
            normalized["answerable"] = True
        elif value in {"false", "0", "no"}:
            normalized["answerable"] = False
    return normalized


def _records_from_path(path: str | Path) -> list[dict[str, Any]]:
    """Load common tabular formats without making heavy dependencies mandatory."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        records: list[dict[str, Any]] = []
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("each JSONL record must be an object")
                records.append(value)
        return records
    if suffix == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        raise ValueError("JSON dataset must be an object or an array of objects")
    if suffix == ".csv":
        with source.open(newline="", encoding="utf-8") as handle:
            return [_normalize_tabular_record(dict(row)) for row in csv.DictReader(handle)]
    if suffix == ".xls":
        raise ValueError("legacy .xls files are not supported; save as .xlsx or CSV")
    if suffix == ".xlsx":
        try:
            import openpyxl
        except ImportError as exc:
            raise ValueError("Excel import requires the optional 'openpyxl' package") from exc
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.values)
        if not rows:
            return []
        headers = [str(value) if value is not None else "" for value in rows[0]]
        return [_normalize_tabular_record(dict(zip(headers, row, strict=False))) for row in rows[1:]]
    if suffix == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise ValueError("Parquet import requires the optional 'pandas' package") from exc
        return pd.read_parquet(source).to_dict(orient="records")
    raise ValueError(f"unsupported dataset format: {source.suffix or '<none>'}; use JSONL, JSON, CSV, XLSX, or Parquet")


def load(path: str | Path, *, reject_duplicates: bool = True) -> list[Sample]:
    """Load JSONL or a supported tabular format with duplicate protection."""
    samples: list[Sample] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    source = Path(path)
    records = _records_from_path(source)
    for line_number, raw_record in enumerate(records, start=1):
        try:
            sample = Sample.model_validate(raw_record)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid dataset record at line {line_number}: {exc}") from exc
        if reject_duplicates and sample.id in seen_ids:
            raise ValueError(f"duplicate sample id at line {line_number}: {sample.id}")
        if reject_duplicates and sample.question in seen_questions:
            raise ValueError(f"duplicate question at line {line_number}: {sample.question!r}")
        seen_ids.add(sample.id)
        seen_questions.add(sample.question)
        samples.append(sample)
    return samples


def iter_load(path: str | Path, *, reject_duplicates: bool = True) -> Iterator[Sample]:
    """Yield validated samples while reading JSONL incrementally."""
    source = Path(path)
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    if source.suffix.lower() not in {".jsonl", ".ndjson"}:
        yield from load(source, reject_duplicates=reject_duplicates)
        return
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw_record = json.loads(line)
                if not isinstance(raw_record, dict):
                    raise ValueError("each JSONL record must be an object")
                sample = Sample.model_validate(raw_record)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid dataset record at line {line_number}: {exc}") from exc
            if reject_duplicates and sample.id in seen_ids:
                raise ValueError(f"duplicate sample id at line {line_number}: {sample.id}")
            if reject_duplicates and sample.question in seen_questions:
                raise ValueError(f"duplicate question at line {line_number}: {sample.question!r}")
            seen_ids.add(sample.id)
            seen_questions.add(sample.question)
            yield sample


def validate(path: str | Path) -> list[str]:
    """Return all dataset problems without stopping at the first one."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    try:
        records = _records_from_path(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    for line_number, raw_record in enumerate(records, start=1):
        try:
            sample = Sample.model_validate(raw_record)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"line {line_number}: {exc}")
            continue
        if sample.id in seen_ids:
            errors.append(f"line {line_number}: duplicate id {sample.id!r}")
        if sample.question in seen_questions:
            errors.append(f"line {line_number}: duplicate question")
        seen_ids.add(sample.id)
        seen_questions.add(sample.question)
    if not errors and not records:
        errors.append("dataset contains no samples")
    return errors


def samples_count(path: str | Path) -> int:
    try:
        source = Path(path)
        if source.suffix.lower() in {".jsonl", ".ndjson"}:
            with source.open(encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        return len(_records_from_path(source))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def manifest(path: str | Path) -> dict[str, Any]:
    """Return a stable dataset manifest suitable for provenance and review."""
    samples = iter_load(path)
    tags: set[str] = set()
    difficulties: set[str] = set()
    ids: list[str] = []
    sample_count = 0
    for sample in samples:
        sample_count += 1
        ids.append(sample.id)
        tags.update(sample.tags)
        difficulties.add(sample.difficulty)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    ids_digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    return {
        "path": str(Path(path)),
        "format": Path(path).suffix.lower().lstrip(".") or "unknown",
        "sample_count": sample_count,
        "sha256": digest,
        "sample_ids_sha256": ids_digest,
        "tags": sorted(tags),
        "difficulties": sorted(difficulties),
    }


def near_duplicate_questions(samples: list[Sample], threshold: float = 0.9) -> list[tuple[str, str, float]]:
    """Find highly similar questions with prefix-index candidate filtering."""
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    tokens = [set(re.findall(r"[\w\u4e00-\u9fff]+", sample.question.lower())) for sample in samples]
    frequencies = Counter(token for values in tokens for token in values)
    ordered = [sorted(values, key=lambda token: (frequencies[token], token)) for values in tokens]
    index_by_token: dict[str, list[int]] = {}
    candidates: set[tuple[int, int]] = set()
    for sample_index, values in enumerate(ordered):
        prefix_length = max(1, len(values) - math.ceil(threshold * len(values)) + 1)
        for token in values[:prefix_length]:
            for other_index in index_by_token.get(token, []):
                size_ratio = min(len(tokens[sample_index]), len(tokens[other_index])) / max(
                    1, max(len(tokens[sample_index]), len(tokens[other_index]))
                )
                if size_ratio >= threshold:
                    candidates.add((sample_index, other_index))
            index_by_token.setdefault(token, []).append(sample_index)
    duplicates: list[tuple[str, str, float]] = []
    for sample_index, other_index in sorted(candidates):
        left, right = tokens[sample_index], tokens[other_index]
        score = len(left & right) / len(left | right) if left | right else 1.0
        if score >= threshold:
            duplicates.append((samples[sample_index].id, samples[other_index].id, round(score, 4)))
    return duplicates


def stratified_sample(samples: list[Sample], limit: int, *, dimension: str = "tags", seed: int | None = None) -> list[Sample]:
    """Select a deterministic round-robin sample across a dataset dimension."""
    if limit < 1:
        return []
    buckets: dict[str, list[Sample]] = {}
    for sample in samples:
        value = getattr(sample, dimension, None)
        if dimension == "tags":
            keys = sample.tags or ["untagged"]
        elif dimension.startswith("metadata."):
            keys = [str(sample.metadata.get(dimension.split(".", 1)[1], "missing"))]
        else:
            keys = [str(value if value is not None else "missing")]
        for key in keys:
            buckets.setdefault(key, []).append(sample)
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected: list[Sample] = []
    selected_ids: set[str] = set()
    keys = sorted(buckets)
    while len(selected) < limit and any(buckets.values()):
        for key in keys:
            while buckets[key] and len(selected) < limit:
                candidate = buckets[key].pop()
                if candidate.id not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(candidate.id)
    return selected


def filter_samples(
    samples: list[Sample],
    *,
    limit: int | None = None,
    include_tags: set[str] | None = None,
    exclude_tags: set[str] | None = None,
    stratify_by: str | None = None,
    seed: int | None = None,
) -> list[Sample]:
    """Apply deterministic filters, optional stratification, and a sample limit."""
    include_tags = include_tags or set()
    exclude_tags = exclude_tags or set()
    filtered = [
        sample
        for sample in samples
        if (not include_tags or include_tags.intersection(sample.tags))
        and not exclude_tags.intersection(sample.tags)
    ]
    if limit and stratify_by:
        return stratified_sample(filtered, limit, dimension=stratify_by, seed=seed)
    return filtered[:limit] if limit else filtered


def validate_benchmark_manifest(path: str | Path) -> list[str]:
    """Validate benchmark paths, content hashes, and declared license evidence."""
    source = Path(path).resolve()
    root = source.parent
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [str(exc)]
    if not isinstance(value, dict) or not isinstance(value.get("datasets"), list):
        return ["benchmark manifest must contain a datasets array"]
    license_file = value.get("license_file")
    errors: list[str] = []
    if not isinstance(license_file, str) or not (root / license_file).is_file():
        errors.append("manifest license_file is missing or does not exist")
    elif "CC0-1.0" not in (root / license_file).read_text(encoding="utf-8"):
        errors.append("manifest license_file does not identify CC0-1.0")
    seen_ids: set[str] = set()
    for index, item in enumerate(value["datasets"], start=1):
        if not isinstance(item, dict):
            errors.append(f"dataset {index} must be an object")
            continue
        dataset_id = str(item.get("id", ""))
        if not dataset_id or dataset_id in seen_ids:
            errors.append(f"dataset {index} has a missing or duplicate id")
        seen_ids.add(dataset_id)
        relative = item.get("path")
        if not isinstance(relative, str):
            errors.append(f"dataset {dataset_id or index} path is missing")
            continue
        dataset_path = (root / relative).resolve()
        if not dataset_path.is_relative_to(root) or not dataset_path.is_file():
            errors.append(f"dataset {dataset_id or index} path is missing or escapes the manifest directory")
            continue
        digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        if item.get("sha256") != digest:
            errors.append(f"dataset {dataset_id or index} sha256 does not match")
        if item.get("license") != "CC0-1.0":
            errors.append(f"dataset {dataset_id or index} must declare CC0-1.0")
        errors.extend(f"dataset {dataset_id or index}: {error}" for error in validate(dataset_path))
    return errors
