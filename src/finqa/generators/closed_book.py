"""Closed-book generator, S0 (ROADMAP P3.0, guide §3.0).

The question goes straight to the model: no retrieval, no tools. The Draft has claims and an
empty evidence set. Doubles as the contamination check: high closed-book accuracy would
mean the model has seen FinanceBench (reused in P7.5).

Config: configs/baselines/s0_closed_book.yaml. Prompts: src/finqa/prompts/s0_*.txt.
The runner calls `generate(question, cfg, ctx)` (finqa.generators.base); the model wrapper is
built once per config and reused for every question.
"""

from __future__ import annotations

import functools
import time

from finqa.config import Config
from finqa.generators.base import Question, RunContext
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

    def __call__(self, question: Question, ctx: RunContext) -> Draft:
        started = time.monotonic()
        qid = question.question_id
        with self.llm.tracer.question(ctx.run_id, qid):
            prompt = messages(
                SYSTEM_PROMPT, USER_PROMPT, company=question.company, question=question.question
            )
            call = answer(self.llm, prompt, ctx.run_id, qid)
        return draft(
            question_id=qid,
            arm=self.cfg.retrieval.arm,
            call=call,
            evidence={},
            trace_id=ctx.trace_id,
            started=started,
        )


@functools.cache
def _generator(cfg: Config) -> ClosedBookGenerator:
    return ClosedBookGenerator(cfg, LLM(cfg))


def generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    """The runner's entry point for the closed_book arm (finqa.eval.runner.GENERATORS)."""
    return _generator(cfg)(question, ctx)
