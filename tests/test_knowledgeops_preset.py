import json

import httpx

from ragproof.adapters.http import HTTPAdapter
from ragproof.config import RunConfig


def test_knowledgeops_preset_maps_real_react_response(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEOPS_API_KEY", "test-key")
    config = RunConfig.load("examples/knowledgeops.yaml")
    assert config.adapter.endpoint == "/ai/react/chat"
    assert config.adapter.json_field == "prompt"
    assert config.adapter.expected_fallback is False

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "prompt": "高温健康风险有哪些？",
            "chatId": "eval-session-001",
            "modelProfile": "quality",
        }
        return httpx.Response(
            200,
            json={
                "answer": "高温风险包括中暑。",
                "evidence": ["高温风险说明"],
                "citations": ["doc-heat"],
                "fallback": False,
            },
        )

    adapter = HTTPAdapter(config.adapter)
    adapter.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    response = adapter.ask("高温健康风险有哪些？")

    assert response.error is None
    assert response.answer == "高温风险包括中暑。"
    assert response.contexts == ["高温风险说明"]
    assert response.citations == ["doc-heat"]
