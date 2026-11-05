"""Closed-book generator, S0 (ROADMAP P3.0, guide §3.0).

The question goes straight to the model: no retrieval, no tools. The Draft has claims and an
empty evidence set. Doubles as the contamination check: high closed-book accuracy would
mean the model has seen FinanceBench (reused in P7.5).

Config: configs/baselines/s0_closed_book.yaml. Prompts: src/finqa/prompts/s0_*.txt.
"""

from __future__ import annotations

import time

from finqa.config import Config
from finqa.generators.common import answer, draft, messages
from finqa.llm import LLM
from finqa.schemas import Draft

SYSTEM_PROMPT = "s0_system.txt"
USER_PROMPT = "s0_user.txt"


class ClosedBookGenerator:
    def __init__(self, cfg: Config, llm: LLM) -> None:
        if cfg.retrieval.arm != "closed_book":
            raise ValueError(f"config {cfg.name!r} is not closed-book: {cfg.retrieval.arm!r}")
        self.cfg = cfg
        self.llm = llm

    def generate(self, question_id: str, company: str, question: str, *, run_id: str) -> Draft:
        started = time.monotonic()
        with self.llm.tracer.question(run_id, question_id) as trace_id:
            prompt = messages(SYSTEM_PROMPT, USER_PROMPT, company=company, question=question)
            call = answer(self.llm, prompt, run_id, question_id)
        return draft(
            question_id=question_id,
            arm=self.cfg.retrieval.arm,
            call=call,
            evidence={},
            trace_id=trace_id,
            started=started,
        )
