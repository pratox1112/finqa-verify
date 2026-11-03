"""Retrieval diagnostic and hit@k (ROADMAP P2.6, guide §2.6; hit@k from the mid-term plan).

Does FinanceBench's gold evidence appear among the chunks a draft saw? Text is normalized
(lowercase, letters and digits only) and cut into word n-grams; a chunk's overlap with one gold
evidence item (one page) is shared n-grams / the smaller side's n-grams. Items are compared one
at a time, because a question can cite several pages (a balance sheet and an income
statement) and a chunk holds part of one. The gold evidence counts as retrieved when some
chunk reaches `diagnostics.evidence_overlap_threshold` for some item (configs/base.yaml;
calibration in docs/DECISIONS.md); how many of the items were found is reported too.
hit@k applies the same test to the top k of one ranked retrieval, with no LLM call, so the
curve over k shows how much more a larger top_k would retrieve.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from finqa.schemas import Chunk, Draft

_WORD = re.compile(r"[a-z0-9]+")


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def overlap(chunk_text: str, gold_text: str, n: int) -> float:
    """Shared n-grams / n-grams of the smaller text (0 when either has none)."""
    c, g = shingles(chunk_text, n), shingles(gold_text, n)
    if not c or not g:
        return 0.0
    return len(c & g) / min(len(c), len(g))


@dataclass(frozen=True)
class RetrievalDiag:
    question_id: str
    gold_evidence_retrieved: bool  # some gold evidence item found in some chunk
    best_chunk_id: str | None
    best_overlap: float
    items_found: int  # gold evidence items found at the threshold
    items: int  # gold evidence items the question has


def chunk_score(chunk: Chunk, gold_evidence: Sequence[str], n: int) -> float:
    """The chunk's best overlap with any one gold evidence item."""
    return max((overlap(chunk.text, item, n) for item in gold_evidence), default=0.0)


def best_match(
    chunks: Sequence[Chunk], gold_evidence: Sequence[str], n: int
) -> tuple[str | None, float]:
    """The chunk that overlaps a gold evidence item most, and that overlap."""
    best_id, best = None, 0.0
    for chunk in chunks:
        score = chunk_score(chunk, gold_evidence, n)
        if score > best:
            best_id, best = chunk.chunk_id, score
    return best_id, best


def diagnose(draft: Draft, gold_evidence: Sequence[str], n: int, threshold: float) -> RetrievalDiag:
    chunks = list(draft.evidence.values())
    chunk_id, best = best_match(chunks, gold_evidence, n)
    found = sum(
        any(overlap(c.text, item, n) >= threshold for c in chunks) for item in gold_evidence
    )
    return RetrievalDiag(
        draft.question_id, best >= threshold, chunk_id, best, found, len(gold_evidence)
    )


def hit_at_k(
    ranked: Sequence[Chunk],
    gold_evidence: Sequence[str],
    ks: Sequence[int],
    n: int,
    threshold: float,
) -> dict[int, bool]:
    """For each k: is a gold-evidence chunk among the first k of `ranked`?"""
    first_hit = next(
        (i + 1 for i, c in enumerate(ranked) if chunk_score(c, gold_evidence, n) >= threshold),
        None,
    )
    return {k: first_hit is not None and first_hit <= k for k in ks}


def hit_curve(per_question: Sequence[dict[int, bool]]) -> dict[int, tuple[int, int]]:
    """k → (questions hit within k, questions)."""
    ks = sorted({k for q in per_question for k in q})
    return {k: (sum(q[k] for q in per_question), len(per_question)) for k in ks}
