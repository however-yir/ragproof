# Security policy

Please report suspected vulnerabilities privately to the repository owner rather than opening a public issue. Include the affected version, reproduction steps, and impact.

`ragproof` sends evaluation questions, answers, and contexts to the configured RAG endpoint and may send answer/context text to the configured judge. Treat run JSON, HTML reports, and judge caches as potentially sensitive. Never commit them when they contain private data.
