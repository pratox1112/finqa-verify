"""V1: LLM self-check, Chain-of-Verification style (ROADMAP P4.2, guide §4.2, §4.4).

The model sees the question, the draft's answer text, its claims and the excerpts they cite
(a computed claim shows its expression and inputs instead), and fills in a `SelfCheck` form:
per claim, supported or not, and a corrected value, unit and period when it can give one.
Corrections are applied to the claims and the revised claims are checked again, up to
`verification.max_revisions` revisions, stopping as soon as a check changes nothing. When the
revisions are used up, one last check flags what is still unsupported, without applying
its corrections (guide §4.4: remaining failures are flagged).

What V1 may change: a claim's value, unit and period. Claim IDs, metrics, citations and
expressions stay as drafted, so the draft's answer claim stays valid. The answer text is not
rewritten (scoring reads the draft's text for text golds; finqa.eval.scoring.score_verified).

A draft that failed or has no claims is returned unchanged without a model call. A model
reply that does not validate is recorded as the result's error, with the claims unchanged.
Every model call goes through finqa.llm (cache, retries, logging). Prompts:
v1_system.txt and v1_user.txt (to be frozen before any test-split run, P4.2).
"""

from __future__ import annotations

import functools
import time
from string import Template

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from finqa.config import Config
from finqa.generators.common import load_prompt
from finqa.generators.rag import excerpt
from finqa.llm import LLM
from finqa.schemas import Claim, Draft, Period, Unit, Verdict, VerifiedResult
from finqa.verifiers.base import result

SYSTEM_PROMPT = "v1_system.txt"
USER_PROMPT = "v1_user.txt"
CHECK = "self_check"


class ClaimCheck(BaseModel):
    claim_id: str
    supported: bool
    corrected_value: float | None = Field(default=None, description="full units; null if none")
    corrected_unit: Unit | None = None
    corrected_period: Period | None = None
    reason: str = Field(description="one short sentence")


class SelfCheck(BaseModel):
    """Your check of every claim in the draft, in the order given."""

    checks: list[ClaimCheck]


def format_claims(claims: list[Claim]) -> str:
    lines = []
    for c in claims:
        line = f"- {c.claim_id}: {c.metric} = {c.value:g} {c.unit}, {c.period}"
        if c.expression:
            line += f"; computed as {c.expression} from {', '.join(c.derived_from) or 'nothing'}"
        line += f"; cites {', '.join(c.chunk_ids)}" if c.chunk_ids else "; cites nothing"
        lines.append(line)
    return "\n".join(lines)


def cited_excerpts(draft: Draft, claims: list[Claim]) -> str:
    """Every excerpt the claims cite, once, in order of first citation. A cited ID that is not
    in the draft's evidence is listed as missing."""
    seen: list[str] = []
    for c in claims:
        seen += [k for k in c.chunk_ids if k not in seen]
    parts = []
    for k in seen:
        chunk = draft.evidence.get(k)
        parts.append(excerpt(chunk, chunk.ticker) if chunk else f"[{k}] (not in the evidence)")
    return "\n\n".join(parts) or "(no excerpts cited)"


def apply(claims: list[Claim], checks: list[ClaimCheck]) -> tuple[list[Claim], bool]:
    """The claims with each unsupported claim's corrections applied; whether any changed."""
    by_id = {c.claim_id: c for c in checks}
    out, changed = [], False
    for claim in claims:
        check = by_id.get(claim.claim_id)
        if check is None or check.supported:
            out.append(claim)
            continue
        update = {
            k: v
            for k, v in (
                ("value", check.corrected_value),
                ("unit", check.corrected_unit),
                ("period", check.corrected_period),
            )
            if v is not None and v != getattr(claim, k)
        }
        out.append(claim.model_copy(update=update))
        changed = changed or bool(update)
    return out, changed


class SelfCheckVerifier:
    def __init__(self, cfg: Config, llm: LLM, questions: dict[str, str] | None = None) -> None:
        if cfg.verification.arm != CHECK:
            raise ValueError(f"config {cfg.name!r} is not V1: {cfg.verification.arm!r}")
        self.cfg = cfg
        self.llm = llm
        self.questions = questions  # question_id -> text; None: read FinanceBench when needed

    def check(self, draft: Draft, claims: list[Claim]) -> tuple[SelfCheck, int, int]:
        prompt = [
            SystemMessage(load_prompt(SYSTEM_PROMPT)),
            HumanMessage(
                Template(load_prompt(USER_PROMPT)).substitute(
                    question=self.question(draft.question_id),
                    answer_text=draft.answer_text,
                    claims=format_claims(claims),
                    excerpts=cited_excerpts(draft, claims),
                )
            ),
        ]
        response = self.llm.invoke(
            prompt, tools=[SelfCheck], tool_choice="SelfCheck", question_id=draft.question_id
        )
        usage = response.usage_metadata
        tokens = (usage["input_tokens"], usage["output_tokens"]) if usage else (0, 0)
        if not response.tool_calls:
            raise ValueError("no SelfCheck tool call in response")
        return SelfCheck.model_validate(response.tool_calls[0]["args"]), *tokens

    def question(self, question_id: str) -> str:
        """The question text (drafts store only its ID)."""
        if self.questions is None:
            self.questions = _questions()
        return self.questions.get(question_id, "(question text not available)")

    def __call__(self, draft: Draft, cfg: Config) -> VerifiedResult:
        started = time.monotonic()
        if draft.error is not None or not draft.claims:
            return result(draft, cfg)
        claims = list(draft.claims)
        verdicts: list[Verdict] = []
        revisions, tokens_in, tokens_out = 0, 0, 0
        flagged: list[str] = []
        try:
            while True:
                checked, t_in, t_out = self.check(draft, claims)
                tokens_in, tokens_out = tokens_in + t_in, tokens_out + t_out
                ids = {c.claim_id for c in claims}
                verdicts += [
                    Verdict(
                        claim_id=c.claim_id,
                        ok=c.supported,
                        check=CHECK,
                        reason=f"round {revisions + 1}: {c.reason}",
                    )
                    for c in checked.checks
                    if c.claim_id in ids
                ]
                flagged = [
                    c.claim_id for c in checked.checks if c.claim_id in ids and not c.supported
                ]
                revised, changed = apply(claims, checked.checks)
                if not changed or revisions >= cfg.verification.max_revisions:
                    break  # nothing to revise, or out of revisions: these flags stand
                claims, revisions = revised, revisions + 1
        except (ValidationError, ValueError) as e:
            return result(
                draft,
                cfg,
                latency_s=round(time.monotonic() - started, 3),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=f"{type(e).__name__}: {e}",
            )
        return result(
            draft,
            cfg,
            claims_after=claims,
            verdicts=verdicts,
            revisions_used=revisions,
            flagged_claim_ids=flagged,
            latency_s=round(time.monotonic() - started, 3),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


@functools.cache
def _questions() -> dict[str, str]:
    from finqa.ingestion import financebench

    return {r["financebench_id"]: r["question"] for r in financebench.load()}


@functools.cache
def _verifier(cfg: Config) -> SelfCheckVerifier:
    return SelfCheckVerifier(cfg, LLM(cfg))


def verify(draft: Draft, cfg: Config) -> VerifiedResult:
    """The runner's entry point for the "self_check" arm (finqa.eval.runner.VERIFIERS)."""
    return _verifier(cfg)(draft, cfg)
