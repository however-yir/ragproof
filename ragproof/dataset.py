"""Dataset loading for ragproof.

Each line in the JSONL file is one evaluation sample:
  {
    "id": "q001",
    "question": "...",
    "ground_truth": "...",           # expected answer (for judge)
    "relevant_doc_ids": ["doc1"]     # for recall/precision metrics (optional)
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, Field


class Sample(BaseModel):
    id: str
    question: str
    ground_truth: str = ""
    relevant_doc_ids: list[str] = Field(default_factory=list)


def load(path: str | Path) -> list[Sample]:
    samples = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            samples.append(Sample.model_validate(json.loads(line)))
    return samples
