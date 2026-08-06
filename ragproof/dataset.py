"""Dataset loading, validation, filtering, and schema helpers."""

from __future__ import annotations

import json
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


def load(path: str | Path, *, reject_duplicates: bool = True) -> list[Sample]:
    """Load JSONL and provide line-aware errors for invalid records."""
    samples: list[Sample] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            sample = Sample.model_validate(json.loads(line))
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
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            sample = Sample.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"line {line_number}: {exc}")
            continue
        if sample.id in seen_ids:
            errors.append(f"line {line_number}: duplicate id {sample.id!r}")
        if sample.question in seen_questions:
            errors.append(f"line {line_number}: duplicate question")
        seen_ids.add(sample.id)
        seen_questions.add(sample.question)
    if not errors and not samples_count(path):
        errors.append("dataset contains no samples")
    return errors


def samples_count(path: str | Path) -> int:
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def filter_samples(
    samples: list[Sample],
    *,
    limit: int | None = None,
    include_tags: set[str] | None = None,
    exclude_tags: set[str] | None = None,
) -> list[Sample]:
    """Apply deterministic tag filters and an optional sample limit."""
    include_tags = include_tags or set()
    exclude_tags = exclude_tags or set()
    filtered = [
        sample
        for sample in samples
        if (not include_tags or include_tags.intersection(sample.tags))
        and not exclude_tags.intersection(sample.tags)
    ]
    return filtered[:limit] if limit else filtered
