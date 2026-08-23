# Security policy

Please use GitHub's **Report a vulnerability** form under the repository Security tab rather than opening a public issue. Include the affected version, reproduction steps, and impact. Private vulnerability reporting is enabled for this repository.

`ragproof` sends evaluation questions, answers, and contexts to the configured RAG endpoint and may send answer/context text to the configured judge. Treat run JSON, HTML reports, and judge caches as potentially sensitive. Never commit them when they contain private data.
