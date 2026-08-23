"""Generate the deterministic, explicitly synthetic public HTTP benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "examples" / "dataset.public-http.en.jsonl"
CORPUS = ROOT / "examples" / "public_benchmark_corpus.jsonl"


def _sample(
    index: int,
    question: str,
    ground_truth: str,
    relevant: list[str],
    category: str,
    *,
    answerable: bool = True,
    relevance_scores: dict[str, float] | None = None,
    negative: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"public-{index:03d}",
        "question": question,
        "ground_truth": ground_truth,
        "relevant_doc_ids": relevant,
        "relevance_scores": relevance_scores or {},
        "negative_doc_ids": negative or [],
        "expected_citations": relevant[:1],
        "tags": ["synthetic", category],
        "difficulty": "hard" if category in {"multihop", "hard-negative"} else "medium",
        "answerable": answerable,
        "metadata": {"source": "ragproof-synthetic-v1", "category": category},
    }


def build() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    samples: list[dict[str, Any]] = []
    corpus: list[dict[str, str]] = []

    for index in range(1, 26):
        code = f"rpcode{index:03d}"
        doc_id = f"doc-{index:03d}"
        text = f"{code} travel reimbursement policy requires approval tier {index % 4 + 1}."
        corpus.append({"id": doc_id, "text": text})
        samples.append(
            _sample(
                index,
                f"What approval tier applies to {code} travel reimbursement?",
                text,
                [doc_id],
                "english",
            )
        )

    for index in range(26, 41):
        code = f"rpcode{index:03d}"
        doc_id = f"doc-{index:03d}"
        text = f"{code} 中文知识库规定数据保留期限为 {index} 天。"
        corpus.append({"id": doc_id, "text": text})
        samples.append(
            _sample(
                index,
                f"{code} 的数据保留期限是多少天？",
                text,
                [doc_id],
                "chinese",
            )
        )

    for index in range(41, 46):
        samples.append(
            _sample(
                index,
                f"UNANSWERABLE rpnone{index:03d} asks for information absent from the corpus.",
                "I cannot answer from the provided context.",
                [],
                "unanswerable",
                answerable=False,
            )
        )

    for index in range(46, 51):
        code = f"rpcode{index:03d}"
        first_id = f"doc-{index:03d}-a"
        second_id = f"doc-{index:03d}-b"
        first = f"{code} retention phase is {index} days."
        second = f"{code} access phase requires role tier {index % 3 + 1}."
        corpus.extend([{"id": first_id, "text": first}, {"id": second_id, "text": second}])
        samples.append(
            _sample(
                index,
                f"Combine the retention and access phases for {code}.",
                first,
                [first_id, second_id],
                "multihop",
                relevance_scores={first_id: 3.0, second_id: 2.0},
            )
        )

    for index in range(51, 56):
        code = f"rpcode{index:03d}"
        doc_id = f"doc-{index:03d}"
        negative_id = f"negative-{index:03d}"
        text = f"{code} verification warranty requires signed evidence level {index % 4 + 1}."
        corpus.extend(
            [
                {"id": doc_id, "text": text},
                {"id": f"support-{index:03d}-a", "text": f"{code} verification reference material."},
                {"id": f"support-{index:03d}-b", "text": f"{code} warranty reference material."},
                {"id": negative_id, "text": "verification warranty marketing copy without signed evidence."},
            ]
        )
        samples.append(
            _sample(
                index,
                f"Which signed evidence level does {code} verification warranty require?",
                text,
                [doc_id],
                "hard-negative",
                negative=[negative_id],
            )
        )

    for index in range(56, 59):
        code = f"rpcode{index:03d}"
        doc_id = f"doc-{index:03d}"
        text = f"{code} citation rule points to evidence record {index}."
        corpus.append({"id": doc_id, "text": text})
        samples.append(
            _sample(index, f"Cite the evidence record for {code}. evidence record", text, [doc_id], "citation")
        )

    for index in range(59, 61):
        code = f"rpcode{index:03d}"
        doc_id = f"doc-{index:03d}"
        text = f"{code} service restoration objective is {index} minutes."
        corpus.append({"id": doc_id, "text": text})
        samples.append(
            _sample(
                index,
                f"In different words, how quickly should {code} return to service?",
                text,
                [doc_id],
                "paraphrase",
            )
        )

    return samples, corpus


def main() -> None:
    samples, corpus = build()
    DATASET.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in samples),
        encoding="utf-8",
    )
    CORPUS.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in corpus),
        encoding="utf-8",
    )
    print(f"generated {len(samples)} samples and {len(corpus)} corpus documents")


if __name__ == "__main__":
    main()
