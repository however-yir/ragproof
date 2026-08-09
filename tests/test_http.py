"""Contract tests for request/response mapping and streaming HTTP behavior."""

import httpx

from ragproof.adapters.http import HTTPAdapter, _dig
from ragproof.config import AdapterConfig


def test_dig_supports_wildcards():
    assert _dig({"items": [{"id": "a"}, {"id": "b"}]}, "items.*.id") == ["a", "b"]


def test_request_template_and_bearer_auth(monkeypatch):
    monkeypatch.setenv("RAGPROOF_TEST_TOKEN", "secret")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"answer": "ok", "contexts": [{"id": "doc-1", "text": "context"}], "citations": ["doc-1"]},
        )

    config = AdapterConfig(
        base_url="http://test",
        endpoint="/answer",
        method="POST",
        bearer_token_env="RAGPROOF_TEST_TOKEN",
        request_template={"query": "{question}"},
        answer_path="answer",
        contexts_path="contexts",
        context_id_path="id",
        citations_path="citations",
    )
    adapter = HTTPAdapter(config)
    adapter.client = httpx.Client(
        base_url="http://test",
        headers={"Authorization": "Bearer secret"},
        transport=httpx.MockTransport(handler),
    )
    response = adapter.ask("hello")
    assert seen["auth"] == "Bearer secret"
    assert '"query":"hello"' in seen["body"]
    assert response.answer == "ok"
    assert response.context_ids == ["doc-1"]
    assert response.citations == ["doc-1"]


def test_streaming_openai_chunks_are_joined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            "data: [DONE]\n",
            headers={"content-type": "text/event-stream"},
        )

    adapter = HTTPAdapter(
        AdapterConfig(
            base_url="http://test",
            endpoint="/stream",
            method="POST",
            json_field="query",
            stream=True,
            answer_path="choices.0.message.content",
        )
    )
    adapter.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    response = adapter.ask("q")
    assert response.answer == "hello"
    assert response.streamed
    assert response.first_token_latency_ms is not None
    assert response.output_char_count == 5


def test_citation_objects_can_map_document_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "ok", "citations": [{"document": {"id": "doc-1"}}]})

    adapter = HTTPAdapter(
        AdapterConfig(
            base_url="http://test",
            endpoint="/answer",
            method="POST",
            answer_path="answer",
            citations_path="citations",
            citation_id_path="document.id",
        )
    )
    adapter.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    assert adapter.ask("q").citations == ["doc-1"]


def test_expected_fallback_rejects_deterministic_degradation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "ok", "fallback": True})

    adapter = HTTPAdapter(
        AdapterConfig(
            base_url="http://test",
            endpoint="/answer",
            method="POST",
            answer_path="answer",
            fallback_path="fallback",
            expected_fallback=False,
        )
    )
    adapter.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))

    response = adapter.ask("q")

    assert response.answer == "ok"
    assert response.error_type == "response_contract"
    assert response.error == "response fallback flag must be false"
