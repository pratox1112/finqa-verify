"""Single-shot RAG generator, R0 (ROADMAP P3.5, guide §3.2), and R0+calc (P3.9).

Resolve the company -> one filtered top-k search -> one structured call producing a Draft
whose claims cite chunk IDs. The evidence is every retrieved chunk. No tools, no second
search: what the first search misses, R0 misses (that is what R1 is compared against).

Search filters come from the question text, the same information the agent gets:
  - company: the FinanceBench company name, through the resolver;
  - fiscal year: the latest year the question mentions (FY2019 - FY2020 -> 2020; a later
    filing also reports the earlier year), as "FY2022", "FY 2022", "FY22" or "2022";
  - form and period: a quarter (Q2, "2Q", "second quarter") means that 10-Q; otherwise a
    year means the 10-K. Q4 is reported in the 10-K.
If the filtered search finds nothing, filters are dropped one at a time (period, then form,
then year); the company filter is kept whenever the company resolved.

The runner calls `generate(question, cfg, ctx)` (finqa.generators.base); the model wrapper,
resolver and index are opened once per config and reused for every question.

The search query is the question itself. R0 retrieves the top_k nearest **tables** plus the
`rag_text_chunks` nearest text chunks (configs/base.yaml): on the dev questions, a plain
top-5 mostly returned prose and notes, while the answers sit in the financial statements
(docs/DECISIONS.md 2026-11-05).

R0+calc (`calculator: true`, configs/ablations/r0_calc_v0.yaml): the same single search and
excerpts, then the model may call `calculate` (the agent's calculator) as often as it needs,
up to `retrieval.max_agent_steps` rounds, before calling Answer. It cannot search again. If it
stops without answering or uses every round, it is asked once more with a forced Answer call
(r1_finalize.txt, as in R1). Its conversation is saved like the agent's, to
runs/<run_id>/agent_traces/<question_id>.json.
"""

from __future__ import annotations

import functools
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from finqa.config import Config
from finqa.generators.base import Question, RunContext
from finqa.generators.common import (
    CALCULATE_DESCRIPTION,
    FINALIZE_PROMPT,
    Answer,
    Calculate,
    Call,
    answer,
    draft,
    function_spec,
    load_prompt,
    messages,
    run_calculate,
    save_trace,
)
from finqa.llm import LLM, REPO_ROOT, is_retryable
from finqa.schemas import Chunk, Draft
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = {False: "r0_system.txt", True: "r0_calc_system.txt"}  # by `calculator`
USER_PROMPT = "r0_user.txt"
CALCULATE_SPEC = function_spec("calculate", Calculate, CALCULATE_DESCRIPTION)

_YEAR = re.compile(r"\bFY\s?(\d{4}|\d{2})\b|\b(20[1-3]\d)\b", re.IGNORECASE)
_QUARTER = re.compile(
    r"\bQ([1-4])\b|\b([1-4])Q\b|\b(first|second|third|fourth) quarter\b", re.IGNORECASE
)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_SCALE = {1e3: "thousands", 1e6: "millions", 1e9: "billions"}


@dataclass(frozen=True)
class Filters:
    fiscal_year: int | None = None
    form: str | None = None
    period: str | None = None


def question_filters(question: str) -> Filters:
    years = []
    for fy, plain in _YEAR.findall(question):
        value = fy or plain
        years.append(int(value) if len(value) == 4 else 2000 + int(value))
    if not years:
        return Filters()
    year = max(years)
    quarters = [
        int(q or n) if (q or n) else _ORDINAL[word.lower()]
        for q, n, word in _QUARTER.findall(question)
    ]
    quarter = max(quarters) if quarters else None
    if quarter is None or quarter == 4:
        return Filters(year, "10-K")
    return Filters(year, "10-Q", f"Q{quarter} FY{year}")


def relaxations(cik: str | None, f: Filters) -> list[dict[str, Any]]:
    """The filter sets to try, strictest first, without repeats."""
    steps: list[dict[str, Any]] = [
        {"cik": cik, "fiscal_year": f.fiscal_year, "form": f.form, "period": f.period},
        {"cik": cik, "fiscal_year": f.fiscal_year, "form": f.form, "period": None},
        {"cik": cik, "fiscal_year": f.fiscal_year, "form": None, "period": None},
        {"cik": cik, "fiscal_year": None, "form": None, "period": None},
    ]
    unique: list[dict[str, Any]] = []
    for s in steps:
        if s not in unique:
            unique.append(s)
    return unique


def excerpt(chunk: Chunk, company: str) -> str:
    """One excerpt for the prompt: a header line, then the chunk text."""
    header = f"[{chunk.chunk_id}] {company} {chunk.form} {chunk.period or chunk.fiscal_year}"
    header += f", {chunk.section}"
    if chunk.is_table:
        scale = _SCALE.get(chunk.unit_scale or 0.0)
        header += f", table in {scale}" if scale else ", table (scale not stated)"
    return f"{header}\n{chunk.text}"


class RagGenerator:
    def __init__(
        self,
        cfg: Config,
        llm: LLM,
        resolver: CompanyResolver,
        search: FilingSearch,
        *,
        traces_root: Path | None = None,
    ) -> None:
        if cfg.retrieval.arm != "rag":
            raise ValueError(f"config {cfg.name!r} is not single-shot RAG: {cfg.retrieval.arm!r}")
        self.cfg = cfg
        self.llm = llm
        self.resolver = resolver
        self.search = search
        self.calculator = cfg.retrieval.calculator
        self.max_steps = cfg.retrieval.max_agent_steps
        self.system_prompt = SYSTEM_PROMPT[self.calculator]
        self.traces_root = traces_root

    def retrieve(self, company: str, question: str) -> list[Chunk]:
        resolution = self.resolver.resolve(company)
        cik = resolution.company.cik if resolution.company else None
        if cik is None:
            logger.warning("company %r did not resolve; searching all companies", company)
        r = self.cfg.retrieval
        for filters in relaxations(cik, question_filters(question)):
            with self.llm.tracer.tool("search_filings", {**filters, "query": question}) as span:
                hits = []
                for is_table, k in ((True, r.top_k), (False, r.rag_text_chunks)):
                    if k:
                        hits += self.search.search_filings(
                            filters["cik"],
                            filters["fiscal_year"],
                            None,
                            question,
                            form=filters["form"],
                            period=filters["period"],
                            is_table=is_table,
                            k=k,
                        )
                if span:
                    span.update(output=[h.chunk_id for h in hits])
            if hits:
                return hits
            logger.info("no chunks for %s; relaxing filters", filters)
        return []

    def __call__(self, question: Question, ctx: RunContext) -> Draft:
        started = time.monotonic()
        qid, company = question.question_id, question.company
        with self.llm.tracer.question(ctx.run_id, qid):
            chunks = self.retrieve(company, question.question)
            text = "\n\n".join(excerpt(c, company) for c in chunks) or "(no excerpts found)"
            prompt = messages(
                self.system_prompt,
                USER_PROMPT,
                company=company,
                question=question.question,
                excerpts=text,
            )
            if self.calculator:
                call = self.calculate_then_answer(prompt, ctx.run_id, qid)
            else:
                call = answer(self.llm, prompt, ctx.run_id, qid)
        return draft(
            question_id=qid,
            arm=self.cfg.retrieval.arm,
            call=call,
            evidence={c.chunk_id: c for c in chunks},
            trace_id=ctx.trace_id,
            started=started,
        )

    def calculate_then_answer(self, prompt: list[BaseMessage], run_id: str, qid: str) -> Call:
        """R0+calc: calculator rounds until the model calls Answer, then that Answer.
        A request the server refuses, or an Answer that does not validate, is the draft's
        error, as in R0 and R1; rate limits and outages are raised."""
        conversation = list(prompt)
        tools: list[Any] = [CALCULATE_SPEC, Answer]
        rounds, tokens_in, tokens_out = 0, 0, 0
        result: Call | None = None
        while rounds < self.max_steps:
            try:
                response = self.llm.invoke(
                    conversation, tools=tools, run_id=run_id, question_id=qid
                )
            except Exception as e:
                if is_retryable(e) or getattr(e, "status_code", None) is None:
                    raise
                result = Call(None, f"{type(e).__name__}: {e}", tokens_in, tokens_out)
                break
            usage = response.usage_metadata
            tokens_in += usage["input_tokens"] if usage else 0
            tokens_out += usage["output_tokens"] if usage else 0
            conversation.append(response)
            final = next((c for c in response.tool_calls if c["name"] == "Answer"), None)
            if final is not None:
                try:
                    a = Answer.model_validate(final["args"])
                    result = Call(a, None, tokens_in, tokens_out)
                except ValidationError as e:
                    result = Call(None, f"{type(e).__name__}: {e}", tokens_in, tokens_out)
                break
            if not response.tool_calls:
                break
            conversation += self._run_calls(response)
            rounds += 1
        if result is None:  # no Answer: it stopped calling tools, or used every round
            nudge = HumanMessage(load_prompt(FINALIZE_PROMPT))
            conversation.append(nudge)
            last = answer(self.llm, conversation, run_id, qid)
            result = Call(
                last.answer, last.error, tokens_in + last.tokens_in, tokens_out + last.tokens_out
            )
        save_trace(
            self.traces_root,
            run_id,
            qid,
            steps_used=rounds,
            max_steps=self.max_steps,
            error=result.error,
            conversation=conversation,
        )
        return result

    def _run_calls(self, message: AIMessage) -> list[ToolMessage]:
        """The reply to each tool call: the calculator's result, or an error the model can act
        on (an invalid expression, a tool R0+calc does not have)."""
        replies = []
        for i, call in enumerate(message.tool_calls):
            if call["name"] != "calculate":
                text = f"Error: unknown tool {call['name']!r}; the tools are calculate and Answer"
            else:
                with self.llm.tracer.tool("calculate", call["args"]) as span:
                    try:
                        text = run_calculate(Calculate.model_validate(call["args"]))
                    except Exception as e:  # reported to the model, which can try again
                        text = f"Error: {type(e).__name__}: {e}"
                    if span:
                        span.update(output=text)
            replies.append(
                ToolMessage(text, tool_call_id=call.get("id") or f"call_{i}", name=call["name"])
            )
        return replies


@functools.cache
def _generator(cfg: Config) -> RagGenerator:
    return RagGenerator(
        cfg,
        LLM(cfg),
        CompanyResolver.from_csv(),
        FilingSearch.open(cfg),
        traces_root=REPO_ROOT / "runs",
    )


def generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    """The runner's entry point for the rag arm (finqa.eval.runner.GENERATORS)."""
    return _generator(cfg)(question, ctx)
