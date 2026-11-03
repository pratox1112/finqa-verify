"""What every generator takes and returns (guide §3).

A generator turns one Question into one Draft (finqa.schemas). The runner, scoring and every
diagnostic read only Drafts, so generators can be built and swapped independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from finqa.config import Config
from finqa.schemas import Draft


@dataclass(frozen=True)
class Question:
    question_id: str  # FinanceBench financebench_id
    company: str
    question: str
    doc_name: str  # e.g. "3M_2018_10K"
    doc_type: str  # "10k" | "10q"
    doc_period: int
    question_type: str  # single_fact | multi_period | calculation | qualitative (splits.json)
    # FinanceBench gold evidence. Only diagnostics and an oracle baseline may read it;
    # retrieval generators must never see it.
    gold_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunContext:
    run_id: str
    thread_id: str  # fresh per question (ROADMAP P2.2), e.g. for the agent's checkpointer
    trace_id: str  # Langfuse trace for this (run, question); goes into Draft.trace_id


class Generator(Protocol):
    def __call__(self, question: Question, cfg: Config, ctx: RunContext) -> Draft: ...
