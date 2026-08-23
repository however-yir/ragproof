"""Validated regression-gate policy shared by CLI, reports, and Actions."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, float] = Field(default_factory=dict)
    max_thresholds: dict[str, float] = Field(default_factory=dict)
    min_deltas: dict[str, float] = Field(default_factory=dict)
    max_relative_drops: dict[str, float] = Field(default_factory=dict)
    group_thresholds: dict[str, float] = Field(default_factory=dict)
    group_max_thresholds: dict[str, float] = Field(default_factory=dict)
    min_sample_count: int | None = None
    min_coverage: dict[str, float] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    allow_provenance_mismatch: bool = False

    @field_validator("max_relative_drops")
    @classmethod
    def non_negative_drops(cls, value: dict[str, float]) -> dict[str, float]:
        if any(item < 0 for item in value.values()):
            raise ValueError("max_relative_drops values must be non-negative")
        return value

    @field_validator("min_coverage")
    @classmethod
    def valid_coverage(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 0 <= item <= 1 for item in value.values()):
            raise ValueError("min_coverage values must be between 0 and 1")
        return value

    @field_validator("min_sample_count")
    @classmethod
    def valid_sample_count(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("min_sample_count must be at least 1")
        return value

    @field_validator("required_fields")
    @classmethod
    def unique_fields(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @classmethod
    def load(cls, path: str | Path) -> GatePolicy:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            raise ValueError("threshold policy must be a mapping")
        return cls.model_validate(value)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    @staticmethod
    def parse_group_mapping(value: dict[str, float]) -> dict[tuple[str, str, str], float]:
        parsed: dict[tuple[str, str, str], float] = {}
        for selector, threshold in value.items():
            parts = selector.split(":", 2)
            if len(parts) != 3 or not all(part.strip() for part in parts):
                raise ValueError(f"invalid group selector {selector!r}; expected dimension:value:metric")
            parsed[tuple(part.strip() for part in parts)] = float(threshold)  # type: ignore[index]
        return parsed

    def merged(
        self,
        *,
        thresholds: dict[str, float] | None = None,
        max_thresholds: dict[str, float] | None = None,
        min_deltas: dict[str, float] | None = None,
        max_relative_drops: dict[str, float] | None = None,
        group_thresholds: dict[tuple[str, str, str], float] | None = None,
        group_max_thresholds: dict[tuple[str, str, str], float] | None = None,
        min_sample_count: int | None = None,
        min_coverage: dict[str, float] | None = None,
        required_fields: Iterable[str] = (),
        allow_provenance_mismatch: bool = False,
    ) -> GatePolicy:
        value = self.model_dump()
        for name, additions in (
            ("thresholds", thresholds),
            ("max_thresholds", max_thresholds),
            ("min_deltas", min_deltas),
            ("max_relative_drops", max_relative_drops),
            ("min_coverage", min_coverage),
        ):
            value[name].update(additions or {})
        for name, group_additions in (
            ("group_thresholds", group_thresholds),
            ("group_max_thresholds", group_max_thresholds),
        ):
            value[name].update(
                {":".join(selector): threshold for selector, threshold in (group_additions or {}).items()}
            )
        if min_sample_count is not None:
            value["min_sample_count"] = min_sample_count
        value["required_fields"] = sorted(set(value["required_fields"]).union(required_fields))
        value["allow_provenance_mismatch"] = bool(
            value["allow_provenance_mismatch"] or allow_provenance_mismatch
        )
        return GatePolicy.model_validate(value)
