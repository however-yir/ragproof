"""Dataset loading, validation, filtering, and schema helpers."""

from __future__ import annotations

import json
import csv
import hashlib
import re
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Sample(BaseModel):
    """One JSONL evaluation sample.

    The extra fields are intentionally data-oriented: tags and difficulty make
    it possible to find regressions in a slice of a dataset, while multiple
    references and expected citations cover real-world QA datasets.
    """

    id: str
    question: str
    ground_truth: str = ""
    ground_truths: list[str] = Field(default_factory=list)
    relevant_doc_ids: list[str] = Field(default_factory=list)
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
    def normalize_references(self) -> "Sample":
        refs = list(dict.fromkeys([ref for ref in [self.ground_truth, *self.ground_truths] if ref]))
        self.ground_truths = refs
        if not self.ground_truth and refs:
            self.ground_truth = refs[0]
        self.tags = sorted(set(tag.strip() for tag in self.tags if tag.strip()))
        return self


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
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix in {".xlsx", ".xls"}:
        try:
            import openpyxl  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("Excel import requires the optional 'openpyxl' package") from exc
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.values)
        if not rows:
            return []
        headers = [str(value) if value is not None else "" for value in rows[0]]
        return [dict(zip(headers, row, strict=False)) for row in rows[1:]]
    if suffix == ".parquet":
        try:
            import pandas as pd  # type: ignore[import-not-found]
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
        return len(_records_from_path(path))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def manifest(path: str | Path) -> dict[str, Any]:
    """Return a stable dataset manifest suitable for provenance and review."""
    samples = load(path)
    tags = sorted({tag for sample in samples for tag in sample.tags})
    difficulties = sorted({sample.difficulty for sample in samples})
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    ids_digest = hashlib.sha256("\n".join(sample.id for sample in samples).encode("utf-8")).hexdigest()
    return {
        "path": str(Path(path)),
        "format": Path(path).suffix.lower().lstrip(".") or "unknown",
        "sample_count": len(samples),
        "sha256": digest,
        "sample_ids_sha256": ids_digest,
        "tags": tags,
        "difficulties": difficulties,
    }


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")
_KEY_RE = re.compile(r"\b(?:sk|pk|ghp|github_pat|AKIA)[A-Za-z0-9_-]{12,}\b")


def redact_text(text: str) -> str:
    """Remove common PII/credential patterns before sharing a dataset."""
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
    return _KEY_RE.sub("[REDACTED_SECRET]", value)


def near_duplicate_questions(samples: list[Sample], threshold: float = 0.9) -> list[tuple[str, str, float]]:
    """Find highly similar questions using a deterministic token Jaccard score."""
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    tokens = [set(re.findall(r"[\w\u4e00-\u9fff]+", sample.question.lower())) for sample in samples]
    duplicates: list[tuple[str, str, float]] = []
    for index, left in enumerate(tokens):
        for other_index in range(index):
            right = tokens[other_index]
            score = len(left & right) / len(left | right) if left | right else 1.0
            if score >= threshold:
                duplicates.append((samples[index].id, samples[other_index].id, round(score, 4)))
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
    rng = random.Random(seed)
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
