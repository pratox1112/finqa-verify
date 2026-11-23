"""V2: grounded verification (ROADMAP P4.3-P4.6, guide §4.3).

Per claim, up to three rule-based checks, each recording a `Verdict` (`ok=None` when the check
cannot run). A claim fails if any check that ran returns `ok=False`. No model judges a claim.

Check 1, cited text (P4.3): does a chunk the claim cites state the claimed value? Numbers are
read with the shared reader (finqa.verifiers.numbers) and put in full units with the chunk's
`unit_scale`; values match within `verification.tolerance` (relative), ignoring sign, because
filings print outflows in parentheses (same as the citation diagnostic, DECISIONS 2026-11-08).

Scale rule (DECISIONS 2026-11-22): a bare number in a table with a stated `unit_scale` counts
only at that scale for a USD claim, so "1,577" in a table "in millions" supports
1,577,000,000 USD and not 1,577 USD (a scale error). For other units the raw value is also
tried, because tables are "in millions, except per share" and may state shares, ratios or
days unscaled. A number with its own scale ("$1.6 billion") or a percentage is never rescaled.

A claim with an `expression` is computed, not quoted: check 1 does not run (check 3 does). A
quoted claim that cites nothing, or cites only chunks the draft never retrieved, fails: V2
accepts a number only if it is grounded in the evidence.
"""

from __future__ import annotations

from finqa.eval.citation_check import _HAS_SCALE
from finqa.eval.scoring import within_tolerance
from finqa.schemas import Chunk, Claim, Draft, Unit, Verdict
from finqa.verifiers.numbers import extract_numbers

CITED_TEXT = "cited_text"


def chunk_values(chunk: Chunk, unit: Unit) -> list[float]:
    """The values `chunk` states, in full units and absolute, as candidates for a claim in
    `unit` (the scale rule above)."""
    values: list[float] = []
    for p in extract_numbers(chunk.text):
        raw = abs(p.value)
        if not chunk.unit_scale or p.unit == "%" or _HAS_SCALE.search(p.text):
            values.append(raw)
            continue
        scaled = raw * chunk.unit_scale
        values += [scaled] if unit == "USD" else [raw, scaled]
    return values


def check_cited_text(claim: Claim, draft: Draft, tolerance: float) -> Verdict:
    def verdict(ok: bool | None, reason: str) -> Verdict:
        return Verdict(claim_id=claim.claim_id, ok=ok, check=CITED_TEXT, reason=reason)

    if claim.expression:
        return verdict(None, "computed claim: checked by recomputation")
    if not claim.chunk_ids:
        return verdict(False, "cites no evidence")
    cited = [draft.evidence[k] for k in claim.chunk_ids if k in draft.evidence]
    if not cited:
        missing = ", ".join(claim.chunk_ids)
        return verdict(False, f"cites {missing}, which is not in the retrieved evidence")
    target = abs(claim.value)
    for chunk in cited:
        if any(within_tolerance(target, v, tolerance) for v in chunk_values(chunk, claim.unit)):
            return verdict(True, f"{claim.value:g} {claim.unit} is stated in {chunk.chunk_id}")
    where = ", ".join(c.chunk_id for c in cited)
    scale = next((c.unit_scale for c in cited if c.unit_scale), None)
    hint = f" (table in units of {scale:g})" if scale else ""
    return verdict(False, f"{claim.value:g} {claim.unit} is not stated in {where}{hint}")
