"""LLM-as-judge metrics via any OpenAI-compatible endpoint (incl. Ollama).

Two metrics:
  faithfulness      — is the answer grounded in the retrieved contexts? (0-1)
  answer_relevancy  — does the answer address the question / ground truth? (0-1)

The judge returns a bare number 0-10 which we normalize to 0-1.
On any error, returns None when skip_on_error is set (graceful degradation).
"""

from __future__ import annotations

import os
import re

import httpx

from ..config import JudgeConfig

_FAITHFULNESS_PROMPT = """You are a strict RAG evaluation judge.
Given retrieved CONTEXTS and an ANSWER, rate from 0 to 10 how well every claim
in the answer is supported by the contexts. 10 = fully grounded, 0 = fabricated.
Reply with ONLY the number.

CONTEXTS:
{contexts}

ANSWER:
{answer}
"""

_RELEVANCY_PROMPT = """You are a strict QA evaluation judge.
Given a QUESTION, a REFERENCE answer (may be empty) and a CANDIDATE answer,
rate from 0 to 10 how well the candidate addresses the question
(consistent with the reference when provided). Reply with ONLY the number.

QUESTION:
{question}

REFERENCE:
{ground_truth}

CANDIDATE:
{answer}
"""


class Judge:
    def __init__(self, config: JudgeConfig):
        self.config = config
        api_key = os.environ.get(config.api_key_env, "ollama")
        self.client = httpx.Client(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=config.timeout,
        )

    def _score(self, prompt: str) -> float | None:
        try:
            resp = self.client.post(
                "/chat/completions",
                json={
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r"\d+(?:\.\d+)?", text)
            if not match:
                return None
            return max(0.0, min(10.0, float(match.group()))) / 10.0
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            if self.config.skip_on_error:
                return None
            raise

    def faithfulness(self, answer: str, contexts: list[str]) -> float | None:
        if not answer or not contexts:
            return None
        return self._score(
            _FAITHFULNESS_PROMPT.format(contexts="\n---\n".join(contexts), answer=answer)
        )

    def answer_relevancy(
        self, question: str, answer: str, ground_truth: str = ""
    ) -> float | None:
        if not answer:
            return None
        return self._score(
            _RELEVANCY_PROMPT.format(
                question=question, ground_truth=ground_truth or "(none)", answer=answer
            )
        )
