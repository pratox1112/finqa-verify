"""Dummy generator and verifier for pipeline tests (ROADMAP P2.2 acceptance, P0.7 smoke test).

The generator always answers 42; the verifier returns the draft's claims unchanged. Neither
calls a model, so the runner, scoring and tables can be tested end to end without the network.
"""

from __future__ import annotations

from finqa.config import Config
from finqa.generators.base import Question, RunContext
from finqa.schemas import Claim, Draft, VerifiedResult


def generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    claim = Claim(
        claim_id="c1", metric="answer", value=42.0, unit="USD", period="FY2022", chunk_ids=[]
    )
    return Draft(
        question_id=question.question_id,
        retrieval_arm="dummy",
        answer_text="42",
        claims=[claim],
        answer_claim_id="c1",
        evidence={},
        trace_id=ctx.trace_id,
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
    )


def verify(draft: Draft, cfg: Config) -> VerifiedResult:
    return VerifiedResult(
        question_id=draft.question_id,
        retrieval_arm=draft.retrieval_arm,
        verification_arm="dummy",
        claims_before=draft.claims,
        claims_after=draft.claims,
        verdicts=[],
        revisions_used=0,
        flagged_claim_ids=[],
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
    )
