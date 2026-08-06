"""Tiny stdlib HTTP server for exercising the generic HTTP adapter locally."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        question = body.get("question") or body.get("query") or body.get("input") or ""
        payload = {
            "answer": f"HTTP mock answer: {question}",
            "contexts": [{"id": "doc1", "text": f"Context for {question}"}],
            "citations": ["doc1"],
        }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    print("mock RAG API listening on http://127.0.0.1:8765")
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
