"""Scoring against FinanceBench gold answers only (ROADMAP P2.3, rule 10; guide §2.3).

Every answer gets one outcome, decided in this order (docs/DECISIONS.md, 2026-11-02):

1. failed:     the generation failed (`error` set) → incorrect, never dropped
2. refused:    no claims and the answer text declines ("cannot determine", "not available", …)
3. numeric:    gold is a single number (`answer_kind == "number"`) → the answer claim's value
               must be within the relative tolerance of the gold value (exact match for a 0 gold)
4. judge:      gold is text, with or without numbers → an LLM judge compares the answer with
               the gold answer (same conclusion; key figures match up to rounding). Its verdicts
               are checked against human labels on a sample.

Never uses a verifier's verdicts or XBRL to decide correctness. Selective accuracy =
correct / (correct + incorrect), i.e. among answers that were not refused.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from finqa.schemas import Claim, Draft, VerifiedResult

AUDIT_PATH = Path(__file__).resolve().parents[3] / "data" / "financebench_audit.csv"
JUDGE_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "judge_v1.txt"

Outcome = Literal["correct", "incorrect", "refused"]
Method = Literal["failed", "refusal", "numeric", "judge"]

REFUSAL = re.compile(
    r"cannot (?:be )?determin|can ?not (?:answer|find|calculate|compute)|unable to"
    r"|not (?:available|provided|disclosed|enough information|possible to determine)"
    r"|insufficient (?:information|data)|no (?:information|data) (?:is )?(?:available|provided)"
    r"|(?:do not|don't) (?:know|have (?:access|enough))"
    # R0 is told "if the excerpts do not contain what you need, say so" (P3.5 prompt).
    r"|(?:excerpts?|filings?|documents?) (?:do|does|did)(?: not|n't)"
    r" (?:contain|include|provide|show)"
    r"|(?:do|does|did)(?: not|n't) (?:contain|include|provide|show|state|disclose|mention)"
    r" (?:the|this|that|any|enough|sufficient|what|a |an |information|data|details)"
    r"|not (?:included|contained|found|shown|stated|mentioned) in the (?:provided )?"
    r"(?:excerpts?|filings?|documents?|information)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Gold:
    question_id: str
    answer: str
    answer_kind: str  # "number" | "text_with_numbers" | "text" (P1.2 audit)
    value: float | None  # set when answer_kind == "number", full units
    unit: str  # schema Unit, or "" when the gold doesn't say


@dataclass(frozen=True)
class AnswerScore:
    question_id: str
    outcome: Outcome
    method: Method
    reason: str = ""


class Judgment(BaseModel):
    """The judge's structured verdict on one answer."""

    correct: bool = Field(description="true if the answer matches the gold answer")
    reason: str = Field(description="one short sentence explaining the verdict")


# question, gold answer, model answer → Judgment
Judge = Callable[[str, str, str], Judgment]


def load_gold(path: Path = AUDIT_PATH) -> dict[str, Gold]:
    with path.open(encoding="utf-8") as f:
        return {
            r["financebench_id"]: Gold(
                question_id=r["financebench_id"],
                answer=r["answer"],
                answer_kind=r["answer_kind"],
                value=float(r["gold_value"]) if r["gold_value"] else None,
                unit=r["gold_unit"],
            )
            for r in csv.DictReader(f)
        }


def within_tolerance(value: float, gold: float, tolerance: float) -> bool:
    """|value - gold| <= tolerance * |gold| (relative to the gold value); a 0 gold needs 0.

    The 1e-9 slack keeps a value exactly at the edge inside despite float rounding."""
    if gold == 0:
        return value == 0
    return abs(value - gold) <= tolerance * abs(gold) * (1 + 1e-9)


def is_refusal(claims: Sequence[Claim], answer_text: str) -> bool:
    return not claims and bool(REFUSAL.search(answer_text))


def score(
    question_id: str,
    question: str,
    gold: Gold,
    claims: Sequence[Claim],
    answer_claim_id: str | None,
    answer_text: str,
    error: str | None,
    tolerance: float,
    judge: Judge | None = None,
) -> AnswerScore:
    if error is not None:
        return AnswerScore(question_id, "incorrect", "failed", error)
    if is_refusal(claims, answer_text):
        return AnswerScore(question_id, "refused", "refusal", answer_text[:200])
    if gold.answer_kind == "number":
        assert gold.value is not None
        claim = next((c for c in claims if c.claim_id == answer_claim_id), None)
        if claim is None:
            return AnswerScore(question_id, "incorrect", "numeric", "no answer claim")
        ok = within_tolerance(claim.value, gold.value, tolerance)
        reason = f"{claim.value:g} {claim.unit} vs gold {gold.value:g} {gold.unit or '?'}"
        return AnswerScore(question_id, "correct" if ok else "incorrect", "numeric", reason)
    if judge is None:
        raise ValueError(f"{question_id}: a text gold answer needs a judge")
    verdict = judge(question, gold.answer, answer_text)
    return AnswerScore(
        question_id, "correct" if verdict.correct else "incorrect", "judge", verdict.reason
    )


def score_draft(
    draft: Draft, question: str, gold: Gold, tolerance: float, judge: Judge | None = None
) -> AnswerScore:
    return score(
        draft.question_id,
        question,
        gold,
        draft.claims,
        draft.answer_claim_id,
        draft.answer_text,
        draft.error,
        tolerance,
        judge,
    )


def score_verified(
    result: VerifiedResult,
    draft: Draft,
    question: str,
    gold: Gold,
    tolerance: float,
    judge: Judge | None = None,
) -> AnswerScore:
    """Score a verified result: its revised claims, the draft's answer text (verification
    doesn't rewrite qualitative answers) and the draft's generation error, if any."""
    return score(
        result.question_id,
        question,
        gold,
        result.claims_after,
        draft.answer_claim_id,
        draft.answer_text,
        draft.error,
        tolerance,
        judge,
    )


def selective_accuracy(scores: Sequence[AnswerScore]) -> tuple[int, int]:
    """(correct, answered): accuracy among answers that were not refused."""
    answered = [s for s in scores if s.outcome != "refused"]
    return sum(s.outcome == "correct" for s in answered), len(answered)


def llm_judge(llm: object, run_id: str | None = None) -> Judge:
    """A Judge backed by finqa.llm.LLM (the configured model, temperature 0, cached)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from finqa.llm import LLM

    if not isinstance(llm, LLM):
        raise TypeError("llm_judge needs a finqa.llm.LLM")
    system = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")

    def judge(question: str, gold_answer: str, model_answer: str) -> Judgment:
        prompt = (
            f"Question:\n{question}\n\nGold answer:\n{gold_answer}\n\nModel answer:\n{model_answer}"
        )
        return llm.structured(
            [SystemMessage(content=system), HumanMessage(content=prompt)], Judgment, run_id=run_id
        )

    return judge
