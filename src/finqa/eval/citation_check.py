"""Numeric citation check (mid-term plan; same idea as the grounded verifier's check 1, P4.3).

For every claim in a draft: does a chunk it cites contain the claimed value? Numbers are read
from the chunk with the shared reader (finqa.verifiers.numbers); a bare number in a table with
a stated `unit_scale` ("in millions") is also tried at that scale. Values match within the
relative tolerance, ignoring sign, because filings print outflows in parentheses. This is a
diagnostic: it never decides correctness (ROADMAP rule 10).

    supported = True    a cited chunk contains the value
    supported = False   cited chunks were checked and none contains it
    supported = None    not checkable: a derived claim (has an expression), no citation, or a
                        cited chunk the draft never saw
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from finqa.eval.scoring import within_tolerance
from finqa.schemas import Chunk, Claim, Draft
from finqa.verifiers.numbers import extract_numbers

_HAS_SCALE = re.compile(r"(?i)(thousand|million|billion|trillion|\d(k|mn|mm|m|bn|b)\b)")


@dataclass(frozen=True)
class CitationCheck:
    question_id: str
    claim_id: str
    supported: bool | None
    reason: str


def chunk_values(chunk: Chunk) -> list[float]:
    """Every value the chunk states, in full units (absolute values)."""
    values: list[float] = []
    for p in extract_numbers(chunk.text):
        values.append(abs(p.value))
        scalable = chunk.unit_scale and p.unit != "%" and not _HAS_SCALE.search(p.text)
        if scalable:
            assert chunk.unit_scale is not None
            values.append(abs(p.value) * chunk.unit_scale)
    return values


def check_claim(claim: Claim, draft: Draft, tolerance: float) -> CitationCheck:
    def result(supported: bool | None, reason: str) -> CitationCheck:
        return CitationCheck(draft.question_id, claim.claim_id, supported, reason)

    if claim.expression:
        return result(None, "derived claim: checked by recomputation, not by citation")
    if not claim.chunk_ids:
        return result(None, "no chunk cited")
    cited = [draft.evidence[c] for c in claim.chunk_ids if c in draft.evidence]
    if not cited:
        return result(None, "cited chunks are not in the draft's evidence")
    for chunk in cited:
        if any(within_tolerance(abs(claim.value), v, tolerance) for v in chunk_values(chunk)):
            return result(True, f"found in {chunk.chunk_id}")
    return result(False, f"not in {len(cited)} cited chunk(s)")


def check_citations(draft: Draft, tolerance: float) -> list[CitationCheck]:
    return [check_claim(c, draft, tolerance) for c in draft.claims]


def citation_precision(checks: Sequence[CitationCheck]) -> tuple[int, int]:
    """(supported, checkable): checkable claims whose cited chunk contains their value."""
    checkable = [c for c in checks if c.supported is not None]
    return sum(bool(c.supported) for c in checkable), len(checkable)
