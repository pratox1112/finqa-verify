"""What every verifier takes and returns (ROADMAP P4.1, guide §4).

A verifier turns one saved Draft into one VerifiedResult (finqa.schemas): the claims before
and after verification, a verdict per check, the revisions used and the claims still flagged.
The runner (`finqa verify`) calls `verify(draft, cfg)` for every draft of a run and writes
runs/<run_id>/verified_<arm>.jsonl. Verified results are scored against gold like drafts
(finqa.eval.scoring.score_verified); a verdict never counts as correctness (guide §4.6).
"""

from __future__ import annotations

from typing import Protocol

from finqa.config import Config
from finqa.schemas import Claim, Draft, Verdict, VerifiedResult


class Verifier(Protocol):
    def __call__(self, draft: Draft, cfg: Config) -> VerifiedResult: ...


def result(
    draft: Draft,
    cfg: Config,
    *,
    claims_after: list[Claim] | None = None,
    verdicts: list[Verdict] | None = None,
    revisions_used: int = 0,
    flagged_claim_ids: list[str] | None = None,
    latency_s: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str | None = None,
) -> VerifiedResult:
    """A VerifiedResult for `draft` under `cfg`'s verification arm. `claims_before` is always
    the draft's claims; `claims_after` defaults to them (nothing changed)."""
    return VerifiedResult(
        question_id=draft.question_id,
        retrieval_arm=draft.retrieval_arm,
        verification_arm=cfg.verification.arm,
        claims_before=list(draft.claims),
        claims_after=list(draft.claims if claims_after is None else claims_after),
        verdicts=verdicts or [],
        revisions_used=revisions_used,
        flagged_claim_ids=flagged_claim_ids or [],
        latency_s=latency_s,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        error=error,
    )
