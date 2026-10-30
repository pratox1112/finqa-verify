"""Propose the 20 model-pilot questions (ROADMAP P0.6) for human approval.

Stratified: 7 metrics-generated, 7 domain-relevant, 6 novel-generated; about 3/4 whose
answer contains a number (so there are numeric claims to extract); 10-K and 10-Q
documents only (the likely P1.1 scope); as many different companies as possible; fixed
seed. These questions are reserved for the dev split (P2.1), so prompts tuned during the
pilot never touch test questions (docs/DECISIONS.md).

    uv run python scripts/select_pilot_questions.py          # writes data/pilot_questions.json
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from finqa.ingestion import financebench

OUT = Path(__file__).resolve().parents[1] / "data" / "pilot_questions.json"
SEED = 2026
QUOTAS = {"metrics-generated": 7, "domain-relevant": 7, "novel-generated": 6}
NUMERIC_SHARE = 0.75
DOC_TYPES = {"10k", "10q"}


def is_numeric_answer(answer: str) -> bool:
    """The gold answer contains a number: "$1577.00", or "Margin fell from 36.8% to 34.6%"."""
    return bool(re.search(r"\d", answer))


def select(records: list[dict[str, Any]], seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pool = sorted(
        (r for r in records if r["doc_type"] in DOC_TYPES), key=lambda r: r["financebench_id"]
    )
    rng.shuffle(pool)
    chosen: list[dict[str, Any]] = []
    companies: set[str] = set()

    def take(candidates: list[dict[str, Any]], k: int) -> None:
        remaining = [r for r in candidates if r not in chosen]
        for _ in range(min(k, len(remaining))):
            remaining.sort(key=lambda r: r["company"] in companies)  # stable: unseen first
            pick = remaining.pop(0)
            chosen.append(pick)
            companies.add(pick["company"])

    for qtype, n in QUOTAS.items():
        of_type = [r for r in pool if r["question_type"] == qtype]
        n_numeric = round(n * NUMERIC_SHARE)
        before = len(chosen)
        take([r for r in of_type if is_numeric_answer(r["answer"])], n_numeric)
        take([r for r in of_type if not is_numeric_answer(r["answer"])], n - n_numeric)
        take(of_type, n - (len(chosen) - before))  # top up if a group ran short
    return chosen


def main() -> int:
    records = financebench.load(financebench.download())
    chosen = select(records)
    entries = [
        {
            "financebench_id": r["financebench_id"],
            "company": r["company"],
            "question_type": r["question_type"],
            "doc_type": r["doc_type"],
            "numeric_answer": is_numeric_answer(r["answer"]),
            "question": r["question"],
        }
        for r in chosen
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "status": "proposed",  # set to "approved" after human review
                "seed": SEED,
                "quotas": QUOTAS,
                "doc_types": sorted(DOC_TYPES),
                "reserved_for": "dev split (P2.1)",
                "questions": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for e in entries:
        kind = "num " if e["numeric_answer"] else "text"
        print(f"{e['financebench_id']}  {e['question_type']:<17} {kind}  {e['company']}")
    print(f"\n{len(entries)} questions, {len({e['company'] for e in entries})} companies -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
