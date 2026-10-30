"""FinanceBench public sample (150 questions; CC-BY-NC-4.0, PatronusAI).

Downloaded once to data/financebench/ (gitignored) and read from there afterwards.
The FinanceBench audit (ROADMAP P1.1) builds on `load()`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from finqa.config import CONFIGS_DIR

URL = (
    "https://huggingface.co/datasets/PatronusAI/financebench/resolve/main/financebench_merged.jsonl"
)
DEFAULT_PATH = CONFIGS_DIR.parent / "data" / "financebench" / "financebench_merged.jsonl"


def download(path: Path = DEFAULT_PATH, url: str = URL) -> Path:
    """Fetch the sample unless it is already on disk (cache-first)."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(path)
    return path


def load(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    """All records, as published (keys include financebench_id, company, doc_name,
    question_type, question, answer, evidence, doc_type, doc_period)."""
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["financebench_id"]: r for r in records}
