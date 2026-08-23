"""Configurable identifier normalization shared by retrieval and citations."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Literal, cast

from .config import IdNormalizationConfig

UnicodeForm = Literal["NFC", "NFD", "NFKC", "NFKD"]


def normalize_id(value: object, config: IdNormalizationConfig) -> str:
    identifier = str(value)
    if config.strip:
        identifier = identifier.strip()
    unicode_form = cast(UnicodeForm, config.unicode_form)
    identifier = unicodedata.normalize(unicode_form, identifier)
    if config.lowercase:
        identifier = identifier.lower()
    for prefix in config.strip_prefixes:
        normalized_prefix = unicodedata.normalize(unicode_form, prefix)
        comparison = identifier.lower() if config.lowercase else identifier
        prefix_comparison = normalized_prefix.lower() if config.lowercase else normalized_prefix
        if comparison.startswith(prefix_comparison):
            identifier = identifier[len(normalized_prefix):]
            break
    return identifier


def normalize_ids(values: Iterable[object], config: IdNormalizationConfig) -> list[str]:
    return [normalized for value in values if (normalized := normalize_id(value, config))]


def normalize_relevance(values: dict[str, float], config: IdNormalizationConfig) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for identifier, score in values.items():
        key = normalize_id(identifier, config)
        if key:
            normalized[key] = max(normalized.get(key, 0.0), float(score))
    return normalized
