"""Single-shot RAG generator, R0 (ROADMAP P3.5, guide §3.2).

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

The search query is the question itself.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from finqa.config import Config
from finqa.generators.common import answer, draft, messages
from finqa.llm import LLM
from finqa.schemas import Chunk, Draft
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "r0_system.txt"
USER_PROMPT = "r0_user.txt"

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
        self, cfg: Config, llm: LLM, resolver: CompanyResolver, search: FilingSearch
    ) -> None:
        if cfg.retrieval.arm != "rag":
            raise ValueError(f"config {cfg.name!r} is not single-shot RAG: {cfg.retrieval.arm!r}")
        if cfg.retrieval.calculator:
            raise ValueError("R0 with the calculator is the R0+calc arm (P3.9), not built yet")
        self.cfg = cfg
        self.llm = llm
        self.resolver = resolver
        self.search = search

    def retrieve(self, company: str, question: str) -> list[Chunk]:
        resolution = self.resolver.resolve(company)
        cik = resolution.company.cik if resolution.company else None
        if cik is None:
            logger.warning("company %r did not resolve; searching all companies", company)
        for filters in relaxations(cik, question_filters(question)):
            with self.llm.tracer.tool("search_filings", {**filters, "query": question}) as span:
                hits = self.search.search_filings(
                    filters["cik"],
                    filters["fiscal_year"],
                    None,
                    question,
                    form=filters["form"],
                    period=filters["period"],
                    k=self.cfg.retrieval.top_k,
                )
                if span:
                    span.update(output=[h.chunk_id for h in hits])
            if hits:
                return hits
            logger.info("no chunks for %s; relaxing filters", filters)
        return []

    def generate(self, question_id: str, company: str, question: str, *, run_id: str) -> Draft:
        started = time.monotonic()
        with self.llm.tracer.question(run_id, question_id) as trace_id:
            chunks = self.retrieve(company, question)
            text = "\n\n".join(excerpt(c, company) for c in chunks) or "(no excerpts found)"
            prompt = messages(
                SYSTEM_PROMPT, USER_PROMPT, company=company, question=question, excerpts=text
            )
            call = answer(self.llm, prompt, run_id, question_id)
        return draft(
            question_id=question_id,
            arm=self.cfg.retrieval.arm,
            call=call,
            evidence={c.chunk_id: c for c in chunks},
            trace_id=trace_id,
            started=started,
        )
