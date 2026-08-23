"""LLM-as-judge metrics via any OpenAI-compatible endpoint (including Ollama)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import JudgeConfig
from ..io import atomic_write_text

_PROMPTS = {
    "faithfulness": """You are a strict RAG evaluation judge. Rate how well every claim in the ANSWER is supported by the CONTEXTS. 10 means fully grounded, 0 means fabricated.
Return JSON only: {{\"score\": number from 0 to 10, \"reason\": \"short explanation\"}}.

CONTEXTS:
{contexts}

ANSWER:
{answer}
""",
    "groundedness": """You are a strict groundedness judge. Separate supported claims from unsupported claims in the ANSWER using only the CONTEXTS. 10 means every material claim is supported.
Return JSON only: {{\"score\": number from 0 to 10, \"reason\": \"short explanation\"}}.

CONTEXTS:
{contexts}

ANSWER:
{answer}
""",
    "context_relevance": """You are a strict retrieval judge. Rate how relevant the CONTEXTS are to the QUESTION. 10 means the contexts directly contain the information needed to answer it.
Return JSON only: {{\"score\": number from 0 to 10, \"reason\": \"short explanation\"}}.

QUESTION:
{question}

CONTEXTS:
{contexts}
""",
    "answer_relevancy": """You are a strict QA judge. Rate how well the CANDIDATE answers the QUESTION, consistent with the REFERENCE when provided.
Return JSON only: {{\"score\": number from 0 to 10, \"reason\": \"short explanation\"}}.

QUESTION:
{question}

REFERENCE:
{ground_truth}

CANDIDATE:
{answer}
""",
}


def calibration_summary(predictions: list[float], labels: list[float]) -> dict[str, float]:
    """Return simple golden-label calibration diagnostics for judge scores."""
    if len(predictions) != len(labels) or not predictions:
        raise ValueError("predictions and labels must have the same non-zero length")
    errors = [float(prediction) - float(label) for prediction, label in zip(predictions, labels, strict=True)]
    return {
        "count": float(len(errors)),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "bias": sum(errors) / len(errors),
        "brier": sum(error * error for error in errors) / len(errors),
    }


@dataclass
class JudgeResult:
    score: float
    reason: str = ""
    raw: str = ""
    cached: bool = False
    model: str = ""
    votes: list[float] | None = None
    tokens: int = 0
    estimated_cost: float = 0.0


class Judge:
    def __init__(self, config: JudgeConfig):
        self.config = config
        api_key = os.environ.get(config.api_key_env, "ollama")
        self.client = httpx.Client(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=config.timeout,
        )
        self._lock = threading.RLock()
        self._request_slots = threading.BoundedSemaphore(config.max_concurrency)
        self._cache: dict[str, dict[str, Any]] = {}
        self._failures = 0
        self._last_request_at = 0.0
        self._cache_path = Path(config.cache_path).expanduser() if config.cache_path else None
        self._load_cache()

    @property
    def models(self) -> list[str]:
        return list(dict.fromkeys(self.config.models or [self.config.model]))

    @property
    def prompt_fingerprint(self) -> str:
        payload = json.dumps({"version": self.config.prompt_version, "overrides": self.config.prompt_overrides}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    @property
    def circuit_open(self) -> bool:
        return self.config.max_failures is not None and self.failures >= self.config.max_failures

    def close(self) -> None:
        self.client.close()

    def _load_cache(self) -> None:
        if not self.config.cache_enabled or not self._cache_path or not self._cache_path.exists():
            return
        try:
            self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self) -> None:
        if not self.config.cache_enabled or not self._cache_path:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._cache_path, json.dumps(self._cache, ensure_ascii=False, indent=2))

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1

    def _throttle(self) -> None:
        interval = self.config.min_request_interval
        if not interval:
            return
        with self._lock:
            remaining = interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _cache_key(self, prompt: str, model: str) -> str:
        payload = json.dumps({"model": model, "prompt": prompt}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse(content: str) -> tuple[float | None, str]:
        try:
            candidate = content.strip()
            if candidate.startswith("```"):
                candidate = candidate.strip("`").removeprefix("json").strip()
            data = json.loads(candidate)
            if isinstance(data, dict):
                score = data.get("score")
                reason = str(data.get("reason", ""))
                if score is not None:
                    return max(0.0, min(10.0, float(score))) / 10.0, reason
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        match = re.search(r"\d+(?:\.\d+)?", content)
        if not match:
            return None, content.strip()
        return max(0.0, min(10.0, float(match.group()))) / 10.0, content.strip()

    def _score(self, prompt: str, model: str) -> JudgeResult | None:
        if self.circuit_open:
            return None
        key = self._cache_key(prompt, model)
        if self.config.cache_enabled:
            with self._lock:
                cached = self._cache.get(key)
            if cached:
                cached_result = dict(cached)
                cached_result["cached"] = True
                return JudgeResult(**cached_result)

        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                with self._request_slots:
                    if self.circuit_open:
                        return None
                    self._throttle()
                    response = self.client.post(
                        "/chat/completions",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0,
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                score, reason = self._parse(str(content))
                if score is None:
                    return None
                usage = payload.get("usage", {}) or {}
                tokens = int(usage.get("total_tokens", 0) or 0)
                result = JudgeResult(
                    score=score,
                    reason=reason,
                    raw=str(content),
                    model=model,
                    tokens=tokens,
                    estimated_cost=tokens / 1000 * self.config.cost_per_1k_tokens,
                )
                if self.config.cache_enabled:
                    with self._lock:
                        self._cache[key] = asdict(result)
                        self._save_cache()
                return result
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
                self._record_failure()
                if self.circuit_open:
                    break
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                    break
                if attempt < self.config.retries and self.config.retry_backoff:
                    time.sleep(self.config.retry_backoff * (2**attempt))
        if self.config.skip_on_error:
            return None
        if last_error:
            raise last_error
        return None

    def _evaluate(self, metric: str, prompt: str) -> JudgeResult | None:
        votes: list[JudgeResult] = []
        for model in self.models:
            result = self._score(prompt, model)
            if result:
                votes.append(result)
        if not votes:
            return None
        scores = [result.score for result in votes]
        score = statistics.median(scores) if self.config.vote == "median" else sum(scores) / len(scores)
        reasons = [result.reason for result in votes if result.reason]
        return JudgeResult(
            score=score,
            reason=" | ".join(reasons),
            raw=" | ".join(result.raw for result in votes),
            cached=all(result.cached for result in votes),
            model=", ".join(result.model for result in votes),
            votes=scores,
            tokens=sum(result.tokens for result in votes),
            estimated_cost=sum(result.estimated_cost for result in votes),
        )

    def _prompt(self, metric: str, **values: str) -> str:
        template = self.config.prompt_overrides.get(metric, _PROMPTS[metric])
        prompt = template.format(**values)
        matches = list(re.finditer(r"[\w\u4e00-\u9fff]+|[^\s\w]", prompt))
        token_limit = self.config.max_prompt_tokens
        if len(matches) > token_limit:
            marker = "\n...[TRUNCATED BY RAGPROOF]...\n"
            marker_tokens = len(re.findall(r"[\w\u4e00-\u9fff]+|[^\s\w]", marker))
            retained = max(2, token_limit - marker_tokens)
            head_count = retained // 2
            tail_count = retained - head_count
            head_end = matches[head_count - 1].end()
            tail_start = matches[-tail_count].start()
            prompt = prompt[:head_end] + marker + prompt[tail_start:]
        limit = self.config.max_prompt_chars
        if len(prompt) <= limit:
            return prompt
        marker = "\n...[TRUNCATED BY RAGPROOF]...\n"
        head = max(0, (limit - len(marker)) // 2)
        tail = max(0, limit - len(marker) - head)
        return prompt[:head] + marker + prompt[-tail:]

    def evaluate_faithfulness(self, answer: str, contexts: list[str]) -> JudgeResult | None:
        if not answer or not contexts:
            return None
        return self._evaluate(
            "faithfulness",
            self._prompt("faithfulness", contexts="\n---\n".join(contexts), answer=answer),
        )

    def evaluate_groundedness(self, answer: str, contexts: list[str]) -> JudgeResult | None:
        if not answer or not contexts:
            return None
        return self._evaluate(
            "groundedness",
            self._prompt("groundedness", contexts="\n---\n".join(contexts), answer=answer),
        )

    def evaluate_context_relevance(self, question: str, contexts: list[str]) -> JudgeResult | None:
        if not question or not contexts:
            return None
        return self._evaluate(
            "context_relevance",
            self._prompt("context_relevance", question=question, contexts="\n---\n".join(contexts)),
        )

    def evaluate_answer_relevancy(self, question: str, answer: str, ground_truth: str = "") -> JudgeResult | None:
        if not answer:
            return None
        return self._evaluate(
            "answer_relevancy",
            self._prompt(
                "answer_relevancy",
                question=question,
                ground_truth=ground_truth or "(none)",
                answer=answer,
            ),
        )

    def faithfulness(self, answer: str, contexts: list[str]) -> float | None:
        result = self.evaluate_faithfulness(answer, contexts)
        return result.score if result else None

    def answer_relevancy(self, question: str, answer: str, ground_truth: str = "") -> float | None:
        result = self.evaluate_answer_relevancy(question, answer, ground_truth)
        return result.score if result else None
