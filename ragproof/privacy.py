"""Recursive secret and PII redaction for shareable configuration and runs."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?key|authorization|auth|bearer|cookie|credential|password|private[_-]?key|secret|token)(?:$|[_-])",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE_RE = re.compile(r"(?<![\w])(?:\+?\d[\d ()-]{7,}\d)(?![\w])")
_KEY_RE = re.compile(r"\b(?:sk|pk|ghp|github_pat|AKIA)[A-Za-z0-9_-]{12,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|api[_-]?key|access[_-]?key|secret|password)=([^&\s]+)"
)


def is_sensitive_key(key: object) -> bool:
    name = str(key).lower()
    if any(safe in name for safe in ("token_count", "tokens_per_second", "tokenizer", "token_path", "max_prompt_chars", "max_prompt_tokens")):
        return False
    return bool(_SENSITIVE_KEY.search(name))


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"***@{hostname}{port}" if parsed.username or parsed.password else parsed.netloc
    query = [
        (key, "***" if is_sensitive_key(key) else redact_text(item))
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment))


def redact_text(text: str) -> str:
    """Redact common credentials and contact PII without hiding normal prose."""
    value = _redact_url(text) if text.startswith(("http://", "https://")) else text
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
    value = _KEY_RE.sub("[REDACTED_SECRET]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED_SECRET]", value)
    return _ASSIGNMENT_RE.sub(r"\1=[REDACTED_SECRET]", value)


def redact_nested(value: Any, *, key: object | None = None) -> Any:
    """Recursively redact sensitive keys and credential-shaped scalar values."""
    if key is not None and is_sensitive_key(key):
        return "***"
    if isinstance(value, dict):
        return {item_key: redact_nested(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_nested(item) for item in value]
    if isinstance(value, tuple):
        return [redact_nested(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
