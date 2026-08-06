# Benchmarking and scope

The mock adapter is a deterministic smoke test, not a quality benchmark. For a meaningful benchmark, publish the dataset schema, sample count, language mix, answerability mix, retrieval gold-label policy, judge model/version, and the exact run configuration.

`ragproof` is a good fit when a deployed RAG API must be tested from the outside and a CI exit code matters. It is less suitable when you need deep pipeline instrumentation, embedding benchmarks, agent trajectory evaluation, or a hosted annotation workflow. Tools such as Ragas and promptfoo have broader ecosystems; ragproof focuses on a small, framework-agnostic, local-first gate.

Recommended benchmark slices: `zh`, `en`, `enterprise`, `hard`, `unanswerable`, and `citation-required`. Compare both overall aggregates and group aggregates so an average does not hide a safety or language-specific regression.
