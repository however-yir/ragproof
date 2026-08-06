# Contributing to ragproof

1. Create a virtual environment and install `pip install -e ".[dev]"`.
2. Run `pytest -q` and `ruff check ragproof tests` before opening a PR.
3. Add a focused test for every behavior change.
4. Keep the CLI backwards compatible unless the PR explicitly documents a breaking change.
5. Do not commit API keys, judge cache files, run outputs, or private evaluation data.

Small adapters should prefer configuration and response-path mapping. Use a plugin entry point when an integration needs custom authentication or streaming behavior.
