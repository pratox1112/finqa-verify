"""Agent generator, R1 (ROADMAP P3.6, guide §3.3); without the calculator it is R1-calc (P3.9).

A LangGraph loop: `agent` asks the model for its next move given the conversation so far, and
the conditional edge sends a tool call to `tools` and anything else to `finalize`:

    START -> agent -> tools -> agent -> ... -> finalize -> END

The model sees the same inputs as R0 (the FinanceBench company name and the question) and
chooses its own calls among:
  - resolve_company(name): name -> CIK (finqa.tools.resolver);
  - search_filings(cik, query, ...): filtered search; every excerpt it returns is added to the
    draft's evidence, in the same excerpt format R0 uses (finqa.tools.search);
  - fetch_filing(cik, form, fiscal_year, quarter): index a missing filing (finqa.tools.fetch);
  - calculate(expression, variables): arithmetic only (finqa.tools.calculate); left out when
    the config has `calculator: false` (the R1-calc arm, with its own system prompt);
  - Answer: the shared answer form (finqa.generators.common.Answer), which ends the loop.

Limits: at most `retrieval.max_agent_steps` tool rounds (configs/base.yaml). If the model
stops calling tools without answering, or runs out of rounds, `finalize` asks once more with a
forced Answer call (prompt r1_finalize.txt). Tool results are cached by their arguments, so a
repeated call costs nothing and returns the same text. Every model call goes through
finqa.llm (cache, retries, logging), so a rerun replays the same conversation from the cache.

State is serializable and checkpointed with MemorySaver, one thread per question
(RunContext.thread_id). Each question's full conversation is written to
runs/<run_id>/agent_traces/<question_id>.json for the trace review (P3.6).
"""

from __future__ import annotations

import functools
import json
import logging
import operator
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

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
from finqa.generators.rag import excerpt
from finqa.llm import LLM, REPO_ROOT, is_retryable
from finqa.schemas import Chunk, Draft
from finqa.tools.fetch import FilingFetcher
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = {True: "r1_system.txt", False: "r1_nocalc_system.txt"}  # by `calculator`
USER_PROMPT = "r1_user.txt"


# --- Tools the model can call -------------------------------------------------------------------


class ResolveCompany(BaseModel):
    name: str = Field(description="company name, brand or ticker")


class SearchFilings(BaseModel):
    cik: str = Field(description='the 10-digit CIK from resolve_company, e.g. "0000066740"')
    query: str = Field(description="what to look for, e.g. 'capital expenditures cash flow'")
    fiscal_year: int | None = Field(default=None, description="the company's fiscal year")
    form: Literal["10-K", "10-Q"] | None = Field(default=None)
    period: str | None = Field(default=None, description='a 10-Q period, e.g. "Q2 FY2023"')
    section: str | None = Field(
        default=None,
        description='10-K: "Item 7" or "Item 8"; 10-Q: "Part I, Item 1" or "Part I, Item 2"',
    )
    tables_only: bool = Field(default=False, description="true: only tables")


CIK = re.compile(r"\d{10}")
TEN_Q_ITEM = re.compile(r"Item (1A|[1-4])")


def section_filter(section: str | None, form: str | None, period: str | None) -> str | None:
    """The section label as indexed. 10-Q sections are stored with their part ("Part I, Item 1"),
    and the index holds only Part I Items 1-4 and Part II Item 1A, so a bare "Item 2" in a 10-Q
    search means "Part I, Item 2" and "Item 1A" means "Part II, Item 1A". A 10-Q search is one
    with form "10-Q" or a quarter period ("Q2 FY2023"). Anything else is passed on unchanged."""
    if section is None or not (form == "10-Q" or (period or "").startswith("Q")):
        return section
    if not TEN_Q_ITEM.fullmatch(section.strip()):
        return section
    item = section.strip()
    return f"Part II, {item}" if item == "Item 1A" else f"Part I, {item}"


class FetchFiling(BaseModel):
    cik: str
    form: Literal["10-K", "10-Q"]
    fiscal_year: int
    quarter: int | None = Field(default=None, description="1, 2 or 3 for a 10-Q")


TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "resolve_company": (ResolveCompany, "Find a company's CIK from its name, brand or ticker."),
    "search_filings": (
        SearchFilings,
        "Search the company's indexed SEC filings. Returns excerpts, each with its ID.",
    ),
    "fetch_filing": (
        FetchFiling,
        "Download and index one 10-K or 10-Q that search_filings cannot find.",
    ),
    "calculate": (Calculate, CALCULATE_DESCRIPTION),
}


def tool_spec(name: str) -> dict[str, Any]:
    """The OpenAI-style function definition the model is given for one tool."""
    return function_spec(name, *TOOLS[name])


def tool_names(calculator: bool) -> list[str]:
    return [n for n in TOOLS if calculator or n != "calculate"]


# --- Graph state --------------------------------------------------------------------------------


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {**a, **b}


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]  # append reducer
    company: dict[str, str] | None  # the last company resolve_company found
    evidence: Annotated[dict[str, dict[str, Any]], _merge]  # chunk_id -> Chunk (as a dict)
    claims: list[dict[str, Any]]  # the final Answer's claims
    answer: dict[str, Any] | None  # the final Answer, as a dict
    steps_used: int  # tool rounds so far
    tokens_in: Annotated[int, operator.add]
    tokens_out: Annotated[int, operator.add]
    error: str | None


def _last_ai(state: AgentState) -> AIMessage | None:
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage):
            return m
    return None


def _answer_call(message: AIMessage | None) -> ToolCall | None:
    if message is None:
        return None
    return next((c for c in message.tool_calls if c["name"] == "Answer"), None)


class AgentGenerator:
    def __init__(
        self,
        cfg: Config,
        llm: LLM,
        resolver: CompanyResolver,
        search: FilingSearch,
        fetcher: FilingFetcher | None = None,
        *,
        traces_root: Path | None = None,
    ) -> None:
        if cfg.retrieval.arm != "agentic":
            raise ValueError(f"config {cfg.name!r} is not the agent: {cfg.retrieval.arm!r}")
        self.cfg = cfg
        self.llm = llm
        self.resolver = resolver
        self.search = search
        self.fetcher = fetcher
        self.traces_root = traces_root
        self.max_steps = cfg.retrieval.max_agent_steps
        self.tools = [tool_spec(n) for n in tool_names(cfg.retrieval.calculator)]
        self.system_prompt = SYSTEM_PROMPT[cfg.retrieval.calculator]
        self._tool_cache: dict[str, tuple[str, list[Chunk], dict[str, str] | None]] = {}
        self.graph = self._build_graph()

    # --- graph -------------------------------------------------------------------------------

    def _build_graph(self) -> Any:
        g: StateGraph[AgentState] = StateGraph(AgentState)
        g.add_node("agent", self._agent)
        g.add_node("tools", self._tools)
        g.add_node("finalize", self._finalize)
        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", self._route, ["tools", "finalize"])
        g.add_conditional_edges("tools", self._after_tools, ["agent", "finalize"])
        g.add_edge("finalize", END)
        return g.compile(checkpointer=MemorySaver())

    def _route(self, state: AgentState) -> str:
        message = _last_ai(state)
        if state["error"] or message is None or not message.tool_calls:
            return "finalize"
        return "finalize" if _answer_call(message) else "tools"

    def _after_tools(self, state: AgentState) -> str:
        return "finalize" if state["steps_used"] >= self.max_steps else "agent"

    # --- nodes -------------------------------------------------------------------------------

    def _invoke(
        self, msgs: list[BaseMessage], tools: list[Any], choice: str | None, qid: str, run_id: str
    ) -> tuple[AIMessage | None, str | None]:
        """One model call; a request the server refuses becomes an error, as in R0
        (finqa.generators.common.answer). Rate limits and outages are raised."""
        try:
            return self.llm.invoke(
                msgs, tools=tools, tool_choice=choice, run_id=run_id, question_id=qid
            ), None
        except Exception as e:
            if is_retryable(e) or getattr(e, "status_code", None) is None:
                raise
            return None, f"{type(e).__name__}: {e}"

    def _agent(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        qid, run_id = config["configurable"]["question_id"], config["configurable"]["run_id"]
        response, error = self._invoke(state["messages"], [*self.tools, Answer], None, qid, run_id)
        if response is None:
            return {"error": error}
        usage = response.usage_metadata
        return {
            "messages": [response],
            "tokens_in": usage["input_tokens"] if usage else 0,
            "tokens_out": usage["output_tokens"] if usage else 0,
        }

    def _tools(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        company_name = config["configurable"]["company"]
        message = _last_ai(state)
        assert message is not None
        results: list[BaseMessage] = []
        evidence: dict[str, dict[str, Any]] = {}
        company = state["company"]
        for i, call in enumerate(message.tool_calls):
            text, chunks, found = self.run_tool(call["name"], call["args"], company_name)
            evidence.update({c.chunk_id: c.model_dump() for c in chunks})
            company = found or company
            results.append(
                ToolMessage(text, tool_call_id=call.get("id") or f"call_{i}", name=call["name"])
            )
        return {
            "messages": results,
            "evidence": evidence,
            "company": company,
            "steps_used": state["steps_used"] + 1,
        }

    def _finalize(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        if state["error"]:
            return {}
        call = _answer_call(_last_ai(state))
        if call is not None:
            try:
                a = Answer.model_validate(call["args"])
            except ValidationError as e:
                return {"error": f"{type(e).__name__}: {e}"}
            return {"answer": a.model_dump(), "claims": [c.model_dump() for c in a.claims]}
        # The model stopped calling tools without answering, or used every round: ask once
        # more, forcing the Answer form.
        qid, run_id = config["configurable"]["question_id"], config["configurable"]["run_id"]
        nudge = HumanMessage(load_prompt(FINALIZE_PROMPT))
        result = answer(self.llm, [*state["messages"], nudge], run_id, qid)
        update: dict[str, Any] = {
            "messages": [nudge],
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "error": result.error,
        }
        if result.answer is not None:
            update["answer"] = result.answer.model_dump()
            update["claims"] = [c.model_dump() for c in result.answer.claims]
        return update

    # --- tools -------------------------------------------------------------------------------

    def run_tool(
        self, name: str, args: dict[str, Any], company_name: str
    ) -> tuple[str, list[Chunk], dict[str, str] | None]:
        """(text for the model, chunks retrieved, company resolved). Cached by arguments.
        A bad call (unknown tool, invalid arguments, a tool error) returns an error message to
        the model instead of failing the question."""
        key = json.dumps([name, args, company_name], sort_keys=True, default=str)
        if key in self._tool_cache:
            return self._tool_cache[key]
        with self.llm.tracer.tool(name, args) as span:
            try:
                result = self._run_tool(name, args, company_name)
            except Exception as e:  # reported to the model, which can try again
                logger.warning("tool %s(%s) failed: %s", name, args, e)
                result = (f"Error: {type(e).__name__}: {e}", [], None)
            if span:
                span.update(output=result[0])
        self._tool_cache[key] = result
        return result

    def _run_tool(
        self, name: str, args: dict[str, Any], company_name: str
    ) -> tuple[str, list[Chunk], dict[str, str] | None]:
        allowed = tool_names(self.cfg.retrieval.calculator)
        if name not in allowed:
            return f"Error: unknown tool {name!r}; the tools are {', '.join(allowed)}", [], None
        handlers: dict[str, Callable[..., tuple[str, list[Chunk], dict[str, str] | None]]] = {
            "resolve_company": self._resolve,
            "search_filings": self._search,
            "fetch_filing": self._fetch,
            "calculate": self._calculate,
        }
        parsed = TOOLS[name][0].model_validate(args)
        return handlers[name](parsed, company_name)

    def _resolve(self, a: ResolveCompany, _: str) -> tuple[str, list[Chunk], dict[str, str] | None]:
        r = self.resolver.resolve(a.name)
        if r.company is not None:
            c = r.company
            found = {"name": c.name, "cik": c.cik, "ticker": c.ticker}
            text = (
                f"{a.name!r} is {c.name} (SEC name {c.sec_name}), CIK {c.cik}, ticker {c.ticker}, "
                f"fiscal year ends {c.fiscal_year_end[:2]}-{c.fiscal_year_end[2:]} (MM-DD)."
            )
            return text, [], found
        options = "; ".join(
            f"{x.company.name} (CIK {x.company.cik}, score {x.score:.0f})" for x in r.candidates
        )
        return (
            f"No single confident match for {a.name!r}. Candidates: {options or 'none'}",
            [],
            None,
        )

    def _search(
        self, a: SearchFilings, company_name: str
    ) -> tuple[str, list[Chunk], dict[str, str] | None]:
        if not CIK.fullmatch(a.cik):
            return (
                f"Error: {a.cik!r} is not a CIK. Pass the 10-digit CIK that resolve_company "
                'returned, e.g. "0000066740".',
                [],
                None,
            )
        hits = self.search.search_filings(
            a.cik,
            a.fiscal_year,
            section_filter(a.section, a.form, a.period),
            a.query,
            form=a.form,
            period=a.period,
            is_table=True if a.tables_only else None,
        )
        if not hits:
            return "No excerpts match these filters.", [], None
        return "\n\n".join(excerpt(c, company_name) for c in hits), hits, None

    def _fetch(self, a: FetchFiling, _: str) -> tuple[str, list[Chunk], dict[str, str] | None]:
        if self.fetcher is None:
            return "Error: fetch_filing is not available in this run.", [], None
        r = self.fetcher.fetch_filing(a.cik, a.form, a.fiscal_year, a.quarter)
        notes = {
            "already_indexed": "is already indexed; search it with search_filings",
            "fetched": f"was fetched and indexed ({r.chunks} chunks); search it now",
            "not_found": "was not found on EDGAR",
            "empty": "was found, but no sections could be read from it",
        }
        return f"{a.form} {r.period} for CIK {a.cik} {notes[r.status]}.", [], None

    def _calculate(self, a: Calculate, _: str) -> tuple[str, list[Chunk], dict[str, str] | None]:
        return run_calculate(a), [], None

    # --- one question ------------------------------------------------------------------------

    def __call__(self, question: Question, ctx: RunContext) -> Draft:
        started = time.monotonic()
        qid = question.question_id
        start: AgentState = {
            "messages": messages(
                self.system_prompt,
                USER_PROMPT,
                company=question.company,
                question=question.question,
            ),
            "company": None,
            "evidence": {},
            "claims": [],
            "answer": None,
            "steps_used": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "error": None,
        }
        config = {
            "configurable": {
                "thread_id": ctx.thread_id,
                "question_id": qid,
                "run_id": ctx.run_id,
                "company": question.company,
            },
            # agent and tools per round, plus finalize, with room to spare
            "recursion_limit": 2 * self.max_steps + 5,
        }
        with self.llm.tracer.question(ctx.run_id, qid):
            final: AgentState = self.graph.invoke(start, config)
        self._save_trace(ctx.run_id, qid, final)
        a = Answer.model_validate(final["answer"]) if final["answer"] else None
        return draft(
            question_id=qid,
            arm=self.cfg.retrieval.arm,
            call=Call(a, final["error"], final["tokens_in"], final["tokens_out"]),
            evidence={k: Chunk.model_validate(v) for k, v in final["evidence"].items()},
            trace_id=ctx.trace_id,
            started=started,
        )

    def _save_trace(self, run_id: str, qid: str, state: AgentState) -> None:
        save_trace(
            self.traces_root,
            run_id,
            qid,
            steps_used=state["steps_used"],
            max_steps=self.max_steps,
            error=state["error"],
            conversation=state["messages"],
        )


@functools.cache
def _generator(cfg: Config) -> AgentGenerator:
    search = FilingSearch.open(cfg)
    return AgentGenerator(
        cfg,
        LLM(cfg),
        CompanyResolver.from_csv(),
        search,
        FilingFetcher(search, cfg.chunking),
        traces_root=REPO_ROOT / "runs",
    )


def generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    """The runner's entry point for the agentic arm (finqa.eval.runner.GENERATORS)."""
    return _generator(cfg)(question, ctx)
