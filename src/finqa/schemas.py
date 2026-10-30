"""Shared data contracts (guide §0.4). Every module imports these; none redefines them.

FROZEN once on main: changes need team approval, two reviews, and the
approved-freeze-change label (ROADMAP rule 5, CONTRIBUTING.md).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Chunk(BaseModel):
    chunk_id: str
    cik: str
    ticker: str
    form: str
    fiscal_year: int
    period: str | None
    section: str
    is_table: bool
    unit_scale: float | None  # 1e3, 1e6, 1e9 or None
    text: str
    source_accession: str


class Claim(BaseModel):
    claim_id: str
    metric: str  # e.g. "total revenue"
    value: float
    unit: str  # "USD", "%", "shares", "ratio"
    period: str  # e.g. "FY2022"
    chunk_ids: list[str]  # evidence cited
    derived_from: list[str] = []  # claim_ids used to compute this one
    expression: str | None = None  # e.g. "(a - b) / b" for derived values


class Draft(BaseModel):
    question_id: str
    retrieval_arm: str
    answer_text: str
    claims: list[Claim]
    evidence: dict[str, Chunk]  # every chunk the generator saw
    trace_id: str
    latency_s: float
    tokens_in: int
    tokens_out: int


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


class ErrorType(str, Enum):  # noqa: UP042  (str values serialize as plain strings)
    WRONG_PERIOD = "wrong_period"
    WRONG_UNIT = "wrong_unit_or_scale"
    WRONG_LINE_ITEM = "wrong_line_item"
    ARITHMETIC = "arithmetic"
    RETRIEVAL_MISS = "retrieval_miss"
    WRONG_COMPANY = "wrong_company"
    OTHER = "other"


class Annotation(BaseModel):
    claim_id: str
    run_id: str
    annotator: str
    correct: bool
    error_type: ErrorType | None
    note: str = ""
