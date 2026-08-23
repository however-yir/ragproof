"""Deterministic stdlib HTTP retrieval service for the public benchmark."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CORPUS_PATH = Path(__file__).with_name("public_benchmark_corpus.jsonl")
CORPUS = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()))


def _score(question: str, document: dict[str, str]) -> tuple[float, str]:
    query_tokens = _tokens(question)
    document_tokens = _tokens(document["text"])
    overlap = len(query_tokens & document_tokens)
    coverage = overlap / max(1, len(query_tokens))
    return coverage, document["id"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"status": "ok"})

    def do_POST(self):  # noqa: N802 - stdlib handler API
        if self.path != "/query":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        question = str(payload.get("question", ""))
        mode = str(payload.get("mode", "normal"))
        top_k = max(1, min(int(payload.get("top_k", 3)), len(CORPUS)))
        if question.startswith("UNANSWERABLE "):
            self._send_json(
                {
                    "answer": "I cannot answer from the provided context.",
                    "contexts": [],
                    "citations": [],
                }
            )
            return
        ranked = sorted(CORPUS, key=lambda document: (-_score(question, document)[0], _score(question, document)[1]))
        if mode == "shuffled":
            ranked.reverse()
        contexts = ranked[:top_k]
        self._send_json(
            {
                "answer": contexts[0]["text"],
                "contexts": contexts,
                "citations": [] if mode == "missing_citations" else [contexts[0]["id"]],
            }
        )

    def _send_json(self, payload: dict):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):  # noqa: A002
        return


if __name__ == "__main__":
    print("public benchmark API listening on http://127.0.0.1:8766", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
