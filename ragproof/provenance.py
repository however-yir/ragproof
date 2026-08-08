"""Reproducibility fingerprints for evaluation runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        return sha256_bytes(handle.read())


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def sha256_values(values: Iterable[str]) -> str:
    return sha256_bytes("\n".join(sorted(values)).encode("utf-8"))
