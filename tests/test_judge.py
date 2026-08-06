"""Judge tests using httpx.MockTransport — no live LLM needed."""

import httpx

from ragproof.config import JudgeConfig
from ragproof.metrics.judge import Judge


def _judge_with_reply(content: str | None, status: int = 200) -> Judge:
    def handler(request: httpx.Request) -> httpx.Response:
        if content is None:
            return httpx.Response(status)
        return httpx.Response(
            status, json={"choices": [{"message": {"content": content}}]}
        )

    judge = Judge(JudgeConfig(enabled=True))
    judge.client = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return judge


def test_score_normalized_to_unit_range():
    judge = _judge_with_reply("8")
    assert judge.faithfulness("answer", ["ctx"]) == 0.8


def test_score_extracts_number_from_text():
    judge = _judge_with_reply("Score: 7.5 out of 10")
    assert judge.answer_relevancy("q", "a") == 0.75


def test_score_clamped_above_ten():
    judge = _judge_with_reply("15")
    assert judge.faithfulness("answer", ["ctx"]) == 1.0


def test_empty_answer_returns_none():
    judge = _judge_with_reply("8")
    assert judge.faithfulness("", ["ctx"]) is None
    assert judge.answer_relevancy("q", "") is None


def test_no_contexts_returns_none():
    judge = _judge_with_reply("8")
    assert judge.faithfulness("answer", []) is None


def test_http_error_skips_gracefully():
    judge = _judge_with_reply(None, status=500)
    assert judge.faithfulness("answer", ["ctx"]) is None


def test_non_numeric_reply_returns_none():
    judge = _judge_with_reply("I cannot rate this.")
    assert judge.faithfulness("answer", ["ctx"]) is None


def test_structured_reason_and_persistent_cache(tmp_path):
    cache = tmp_path / "judge-cache.json"
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"score": 9, "reason": "supported"}'}}]})

    config = JudgeConfig(enabled=True, cache_path=str(cache), cache_enabled=True)
    first = Judge(config)
    first.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    result = first.evaluate_faithfulness("answer", ["ctx"])
    assert result and result.score == 0.9 and result.reason == "supported"

    second = Judge(config)
    second.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    cached = second.evaluate_faithfulness("answer", ["ctx"])
    assert cached and cached.cached
    assert calls["count"] == 1
