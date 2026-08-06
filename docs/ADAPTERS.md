# Adapter guide

The generic HTTP adapter supports query parameters, JSON fields, nested request templates, Bearer authentication, wildcard response paths, retries, and streamed OpenAI-style chunks.

Built-in presets:

| `type` | Defaults |
|---|---|
| `langserve` / `langchain` | `POST /invoke`, JSON `input`, answer `output` |
| `llamaindex` | `POST /query`, JSON `query`, answer `response` |
| `dify` | `POST /v1/chat-messages`, JSON `query`, answer `answer` |
| `openai` | `POST /chat/completions`, request template with `messages`, answer `choices.0.message.content` |

For example, array paths can use `metadata.retriever_resources.*.document_id`. If an integration needs custom behavior, publish a Python package with the `ragproof.adapters` entry-point group:

```toml
[project.entry-points."ragproof.adapters"]
my_rag = "my_package:build_adapter"
```

See `examples/` for LangServe, Dify, OpenAI-compatible, and the local mock server configurations.
