"""Shared data contracts (guide §0.4). Every module imports these; none redefines them.

FROZEN once on main: changes need team approval, two reviews, and the
approved-freeze-change label (ROADMAP rule 5, CONTRIBUTING.md).

Conventions (docs/DECISIONS.md, 2026-10-30 schema review):
  - Claim IDs are short and local to a draft ("c1", "c2"); an annotation is identified by
    (run_id, question_id, claim_id). A revised claim keeps its claim_id.
  - Values are in full units, never pre-scaled ($394.3B is 394300000000); percentages are
    the percent number (12.5% is 12.5).
  - Periods use the company's own fiscal year: "FY2022", "Q3 FY2022", or year-to-date
    "6M FY2022" / "9M FY2022".
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Unit = Literal["USD", "USD/share", "%", "shares", "ratio", "days"]
Period = Annotated[str, Field(pattern=r"^(FY\d{4}|Q[1-4] FY\d{4}|[69]M FY\d{4})$")]


class Chunk(BaseModel):
    chunk_id: str
    cik: str
    ticker: str
    form: str
    fiscal_year: int
    period: Period | None
    section: str
    is_table: bool
    unit_scale: float | None  # 1e3, 1e6, 1e9 or None
    text: str
    source_accession: str


class Claim(BaseModel):
    claim_id: str
    metric: str  # e.g. "total revenue"
    value: float  # full units; percentages as 12.5, not 0.125
    unit: Unit
    period: Period
    chunk_ids: list[str]  # evidence cited
    derived_from: list[str] = []  # claim_ids used to compute this one
    expression: str | None = None  # e.g. "(a - b) / b" for derived values


class Draft(BaseModel):
    question_id: str
    retrieval_arm: str
    answer_text: str
    claims: list[Claim]
    answer_claim_id: str | None = None  # the claim that answers the question; None if qualitative
    evidence: dict[str, Chunk]  # every chunk the generator saw
    trace_id: str
    latency_s: float
    tokens_in: int
    tokens_out: int
    error: str | None = None  # set when generation failed; scored as incorrect, never dropped


class Verdict(BaseModel):
    claim_id: str
    ok: bool | None  # None = check could not run
    check: str  # "cited_text" | "xbrl" | "recompute" | "self_check"
    reason: str


class VerifiedResult(BaseModel):
    question_id: str
    retrieval_arm: str
    verification_arm: str
    claims_before: list[Claim]
    claims_after: list[Claim]
    verdicts: list[Verdict]
    revisions_used: int
    flagged_claim_ids: list[str]
    latency_s: float
    tokens_in: int
    tokens_out: int
    error: str | None = None  # set when verification failed; then claims_after = claims_before


class ErrorType(str, Enum):  # noqa: UP042  (str values serialize as plain strings)
    WRONG_PERIOD = "wrong_period"
    WRONG_UNIT = "wrong_unit_or_scale"
    WRONG_LINE_ITEM = "wrong_line_item"
    ARITHMETIC = "arithmetic"
    RETRIEVAL_MISS = "retrieval_miss"
    WRONG_COMPANY = "wrong_company"
    OTHER = "other"


class Annotation(BaseModel):
    question_id: str
    claim_id: str
    run_id: str
    annotator: str
    correct: bool
    error_type: ErrorType | None
    note: str = ""
