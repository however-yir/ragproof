# Benchmarking and scope

The mock adapter is a deterministic smoke test, not a quality benchmark. For a meaningful benchmark, publish the dataset schema, sample count, language mix, answerability mix, retrieval gold-label policy, judge model/version, and the exact run configuration.

## Reproducible public HTTP benchmark

The repository includes a small, deterministic benchmark that exercises the real HTTP adapter rather than the in-process mock adapter:

- corpus: `examples/public_benchmark_corpus.jsonl` (8 synthetic enterprise-policy documents, CC0-1.0)
- questions: `examples/dataset.public-http.en.jsonl` (8 English questions with gold document and citation IDs, CC0-1.0)
- manifest/license: `examples/benchmark-manifest.json` and `examples/BENCHMARK_LICENSE.md` (paths, SHA-256 values, and CC0 evidence checked in CI)
- service: `examples/public_benchmark_server.py` (stdlib lexical retrieval, no model or network dependency)
- configuration: `examples/public-http-benchmark.yaml`
- known-good run: `examples/baselines/public-http-v0.4.1.json`

Run the same gate locally:

```bash
python examples/public_benchmark_server.py &
server_pid=$!
trap 'kill "$server_pid"' EXIT

ragproof run -c examples/public-http-benchmark.yaml -o runs/public-http-current.json
ragproof compare \
  --baseline examples/baselines/public-http-v0.4.1.json \
  --current runs/public-http-current.json \
  --threshold 'recall@3=1.0' \
  --threshold 'mrr=1.0' \
  --threshold 'citation_validity=1.0' \
  --max 'error_rate=0.0'
```

This benchmark proves the HTTP request/response mapping, ranking metrics, citations, provenance checks, and CI failure behavior are reproducible. It is intentionally small and synthetic; it does not claim to predict production quality or compare model vendors.

`ragproof` is a good fit when a deployed RAG API must be tested from the outside and a CI exit code matters. It is less suitable when you need deep pipeline instrumentation, embedding benchmarks, agent trajectory evaluation, or a hosted annotation workflow. Tools such as Ragas and promptfoo have broader ecosystems; ragproof focuses on a small, framework-agnostic, local-first gate.

Recommended benchmark slices: `zh`, `en`, `enterprise`, `hard`, `unanswerable`, and `citation-required`. Compare both overall aggregates and group aggregates so an average does not hide a safety or language-specific regression.
