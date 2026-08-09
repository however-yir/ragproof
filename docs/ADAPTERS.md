# Adapter guide

The generic HTTP adapter supports query parameters, JSON fields, nested request templates, Bearer authentication, wildcard response paths, retries, and streamed OpenAI-style chunks. Streaming requests are consumed incrementally and report first-token latency.

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

Structured citations can be mapped explicitly when the response returns objects instead of strings:

```yaml
citations_path: data.citations
citation_id_path: document.id
citation_text_path: title
```

When an API explicitly tells clients that it returned a deterministic fallback,
make that part of the evaluation contract instead of inferring it from answer
text:

```yaml
fallback_path: fallback
expected_fallback: false
```

With this mapping, `fallback: true`, a missing field, or a non-boolean value
becomes a `response_contract` error for the sample. The bundled
`examples/knowledgeops.yaml` uses this for `/ai/react/chat`.

The report records `first_token_latency_ms`, total latency, and output character count for streamed responses. Character count is intentionally used instead of a tokenizer-specific token count so the adapter remains framework-agnostic.
