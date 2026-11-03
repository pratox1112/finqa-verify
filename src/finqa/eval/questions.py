"""Questions for a split: FinanceBench records joined with data/splits.json (ROADMAP P2.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finqa.generators.base import Question
from finqa.ingestion import financebench

SPLITS_PATH = Path(__file__).resolve().parents[3] / "data" / "splits.json"


def load_splits(path: Path = SPLITS_PATH) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def to_question(record: dict[str, Any], question_type: str) -> Question:
    evidence = tuple(
        e["evidence_text"] for e in record.get("evidence") or [] if e.get("evidence_text")
    )
    return Question(
        question_id=record["financebench_id"],
        company=record["company"],
        question=record["question"],
        doc_name=record["doc_name"],
        doc_type=record["doc_type"],
        doc_period=int(record["doc_period"]),
        question_type=question_type,
        gold_evidence=evidence,
    )


def load_questions(
    split: str,
    splits_path: Path = SPLITS_PATH,
    financebench_path: Path = financebench.DEFAULT_PATH,
) -> list[Question]:
    """Questions of `split` ("dev" or "test"), in the order splits.json lists them."""
    splits = load_splits(splits_path)
    if split not in ("dev", "test"):
        raise ValueError(f"unknown split {split!r}")
    records = financebench.by_id(financebench.load(financebench_path))
    missing = [q for q in splits[split] if q not in records]
    if missing:
        raise ValueError(
            f"{len(missing)} {split} questions not in FinanceBench, e.g. {missing[:3]}"
        )
    types = splits["question_types"]
    return [to_question(records[q], types[q]) for q in splits[split]]
