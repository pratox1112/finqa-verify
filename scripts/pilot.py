"""Model pilot (ROADMAP P0.6): does the model call tools and return valid structured output?

On the approved pilot questions (data/pilot_questions.json), with FinanceBench's gold
evidence standing in for retrieval (nothing is indexed yet):

  A. Tool calling. Two dummy tools: SearchFilings (returns the question's gold evidence)
     and Calculate (evaluates arithmetic). Up to MAX_STEPS model turns per question.
     A tool call is valid if it names a defined tool and its arguments validate against
     that tool's schema. A Groq `tool_use_failed` error counts as one invalid call, and a
     question where the model never calls a tool counts as one invalid call.
  B. Structured output. One forced PilotAnswer tool call per question (same mechanism as
     LLM.structured); valid if it parses and every claim uses the shared Unit and Period
     formats from finqa.schemas.

Targets: >= 95% for both. Measures tokens per call. Writes docs/PILOT.md and
runs/pilot/<run_id>/results.jsonl. Real Groq calls; responses are cached, so reruns are free.

    uv run python scripts/pilot.py
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import operator
import statistics
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import groq
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field, ValidationError

from finqa.config import BASE_CONFIG, load_config
from finqa.ingestion import financebench
from finqa.llm import LLM
from finqa.schemas import Period, Unit

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data" / "pilot_questions.json"
REPORT = ROOT / "docs" / "PILOT.md"
MAX_STEPS = 4
TARGET = 0.95


# --- Dummy tools -------------------------------------------------------------------------


class SearchFilings(BaseModel):
    """Search a company's SEC filings and return the most relevant text passages."""

    company: str = Field(description="Company name, e.g. '3M'")
    fiscal_year: int = Field(description="Fiscal year of the filing, e.g. 2022")
    query: str = Field(description="What to look for, e.g. 'capital expenditures'")


class Calculate(BaseModel):
    """Evaluate an arithmetic expression over named numbers and return the result."""

    expression: str = Field(description="Arithmetic using the variable names, e.g. '(a - b) / b'")
    variables: dict[str, float] = Field(
        default_factory=dict, description="Value of each name in the expression"
    )


TOOLS: dict[str, type[BaseModel]] = {"SearchFilings": SearchFilings, "Calculate": Calculate}

_OPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def arithmetic(expression: str, variables: dict[str, float]) -> float:
    """Evaluate + - * / ** and parentheses over numbers and the given names; nothing else."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in variables:
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"not allowed in an arithmetic expression: {ast.dump(node)[:60]}")

    return ev(ast.parse(expression, mode="eval"))


def validate_tool_call(call: dict[str, Any]) -> str | None:
    """None if the call names a defined tool with schema-valid arguments, else the reason."""
    schema = TOOLS.get(call.get("name", ""))
    if schema is None:
        return f"unknown tool {call.get('name')!r}"
    try:
        schema.model_validate(call.get("args", {}))
    except ValidationError as e:
        return f"invalid arguments: {e.errors()[0]['msg']}"
    return None


NO_NEW_PASSAGES = "No new passages found; use the evidence already returned."


def run_tool(call: dict[str, Any], evidence: str, searched_before: bool = False) -> str:
    """SearchFilings returns the gold evidence once; later searches return a short note, so
    the conversation doesn't grow by a full copy of the evidence per search."""
    if call["name"] == "SearchFilings":
        return NO_NEW_PASSAGES if searched_before else evidence
    args = Calculate.model_validate(call["args"])
    try:
        return str(arithmetic(args.expression, args.variables))
    except (ValueError, ZeroDivisionError, SyntaxError) as e:
        return f"error: {e}"


# --- Structured output schema --------------------------------------------------------------


class PilotClaim(BaseModel):
    metric: str = Field(description="What the number is, e.g. 'capital expenditures'")
    value: float = Field(description="Full units: $1.2 billion is 1200000000; 12.5% is 12.5")
    unit: Unit
    period: Period = Field(description="FY2022, Q3 FY2022, 6M FY2022 or 9M FY2022")


class PilotAnswer(BaseModel):
    """The answer to the question and every figure it relies on."""

    answer_text: str = Field(description="One or two sentences answering the question")
    claims: list[PilotClaim] = Field(description="Every number in the answer; [] if none")


# --- Prompts -----------------------------------------------------------------------------

TOOL_SYSTEM = (
    "You answer questions about companies' SEC filings. First call SearchFilings to get "
    "evidence. Use Calculate for any arithmetic. When you have what you need, answer in one "
    "or two sentences without calling a tool."
)
STRUCTURED_SYSTEM = (
    "Answer the question from the evidence and list every figure your answer uses. "
    "Units: USD, USD/share, %, shares, ratio or days. Values in full units ($1.2 billion = "
    "1200000000; $3.45 per share = 3.45 with unit USD/share); percentages as numbers "
    "(12.5% = 12.5). Periods as FY2022, Q3 FY2022, 6M FY2022 or 9M FY2022, using the "
    "company's own fiscal year. If the answer has no numbers, return an empty claims list."
)


def evidence_text(record: dict[str, Any]) -> str:
    return "\n\n".join(e["evidence_text"] for e in record["evidence"])


def too_large(error: Exception) -> bool:
    """HTTP 413: the request exceeds the account's per-minute token limit on its own (a Groq
    plan limit, not a model failure). Reported separately and left out of the rates."""
    return isinstance(error, groq.APIStatusError) and error.status_code == 413


def _tokens(message: AIMessage) -> int:
    usage = message.usage_metadata
    return (usage["input_tokens"] + usage["output_tokens"]) if usage else 0


def tool_test(llm: LLM, record: dict[str, Any], run_id: str) -> dict[str, Any]:
    qid = record["financebench_id"]
    messages: list[BaseMessage] = [
        SystemMessage(TOOL_SYSTEM),
        HumanMessage(f"Company: {record['company']}\nQuestion: {record['question']}"),
    ]
    calls, invalid, tokens = 0, [], []
    searched = False
    for _ in range(MAX_STEPS):
        try:
            response = llm.invoke(
                messages, tools=list(TOOLS.values()), run_id=run_id, question_id=qid
            )
        except groq.APIStatusError as e:
            if too_large(e):
                return {
                    "tool_calls": 0,
                    "invalid_tool_calls": [],
                    "tool_tokens": tokens,
                    "tool_too_large": True,
                }
            if not isinstance(e, groq.BadRequestError):
                raise
            calls += 1  # e.g. tool_use_failed: the model produced a malformed tool call
            invalid.append(f"groq error: {str(e)[:120]}")
            break
        tokens.append(_tokens(response))
        messages.append(response)
        if not response.tool_calls:
            break
        for call in response.tool_calls:
            calls += 1
            reason = validate_tool_call(call)
            if reason:
                invalid.append(reason)
            if reason is None:
                content = run_tool(call, evidence_text(record), searched_before=searched)
                searched = searched or call["name"] == "SearchFilings"
            else:
                content = reason
            messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
    if calls == 0:
        calls, invalid = 1, ["answered without calling a tool"]
    return {
        "tool_calls": calls,
        "invalid_tool_calls": invalid,
        "tool_tokens": tokens,
        "tool_too_large": False,
    }


def structured_test(llm: LLM, record: dict[str, Any], run_id: str) -> dict[str, Any]:
    messages = [
        SystemMessage(STRUCTURED_SYSTEM),
        HumanMessage(
            f"Company: {record['company']}\nQuestion: {record['question']}\n\n"
            f"Evidence:\n{evidence_text(record)}"
        ),
    ]
    try:
        response = llm.invoke(
            messages,
            tools=[PilotAnswer],
            tool_choice="PilotAnswer",
            run_id=run_id,
            question_id=record["financebench_id"],
        )
    except groq.APIStatusError as e:
        if too_large(e):
            return {
                "structured_valid": False,
                "structured_error": None,
                "structured_tokens": None,
                "structured_too_large": True,
            }
        if not isinstance(e, groq.BadRequestError):
            raise
        return {
            "structured_valid": False,
            "structured_error": f"groq error: {str(e)[:120]}",
            "structured_tokens": None,
            "structured_too_large": False,
        }
    error = None
    if not response.tool_calls:
        error = "no PilotAnswer tool call"
    else:
        try:
            PilotAnswer.model_validate(response.tool_calls[0]["args"])
        except ValidationError as e:
            err = e.errors()[0]
            error = f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
    return {
        "structured_valid": error is None,
        "structured_error": error,
        "structured_tokens": _tokens(response),
        "structured_too_large": False,
    }


# --- Summary and report ------------------------------------------------------------------


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Rates leave out requests too large for the account's token limit (counted separately)."""
    tool_runs = [r for r in results if not r.get("tool_too_large")]
    struct_runs = [r for r in results if not r.get("structured_too_large")]
    calls = sum(r["tool_calls"] for r in tool_runs)
    bad_calls = sum(len(r["invalid_tool_calls"]) for r in tool_runs)
    valid_struct = sum(r["structured_valid"] for r in struct_runs)
    tool_tokens = [t for r in results for t in r["tool_tokens"]]
    struct_tokens = [r["structured_tokens"] for r in results if r["structured_tokens"]]
    all_tokens = tool_tokens + struct_tokens

    def stats(xs: list[int]) -> dict[str, float]:
        return {"mean": statistics.mean(xs), "max": max(xs)} if xs else {"mean": 0, "max": 0}

    return {
        "questions": len(results),
        "tool_calls": calls,
        "valid_tool_calls": calls - bad_calls,
        "tool_call_rate": (calls - bad_calls) / calls if calls else 0.0,
        "structured_valid": valid_struct,
        "structured_questions": len(struct_runs),
        "structured_rate": valid_struct / len(struct_runs) if struct_runs else 0.0,
        "tool_too_large": len(results) - len(tool_runs),
        "structured_too_large": len(results) - len(struct_runs),
        "tokens_all": stats(all_tokens),
        "tokens_tool": stats(tool_tokens),
        "tokens_structured": stats(struct_tokens),
    }


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}, {100 * n / d:.1f}%" if d else "0/0"


def render_report(summary: dict[str, Any], results: list[dict[str, Any]], meta: dict) -> str:
    passed = summary["tool_call_rate"] >= TARGET and summary["structured_rate"] >= TARGET
    lines = [
        "# Model pilot (ROADMAP P0.6)",
        "",
        f"Run `{meta['run_id']}` on {meta['date']}. Model `{meta['model_id']}`, thinking "
        f"`{meta['thinking']}`, temperature {meta['temperature']}. Generated by "
        "`scripts/pilot.py`; do not edit by hand.",
        "",
        f"**Result: {'PASS' if passed else 'BELOW TARGET'}** (target >= {TARGET:.0%} on both).",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Tool-call success | {_pct(summary['valid_tool_calls'], summary['tool_calls'])} |",
        "| Structured-output validity | "
        f"{_pct(summary['structured_valid'], summary['structured_questions'])} |",
        "| Skipped: request too large for the Groq plan (HTTP 413) | "
        f"tool test {summary['tool_too_large']}, structured test "
        f"{summary['structured_too_large']} (of {summary['questions']}) |",
        f"| Tokens per call, all | mean {summary['tokens_all']['mean']:.0f}, max "
        f"{summary['tokens_all']['max']} |",
        f"| Tokens per call, tool turns | mean {summary['tokens_tool']['mean']:.0f}, max "
        f"{summary['tokens_tool']['max']} |",
        f"| Tokens per call, structured | mean {summary['tokens_structured']['mean']:.0f}, max "
        f"{summary['tokens_structured']['max']} |",
        "",
        "## Method",
        "",
        f"- {summary['questions']} approved questions from `data/pilot_questions.json` "
        "(reserved for the dev split). FinanceBench's gold evidence stands in for retrieval.",
        f"- Tool calling: dummy `SearchFilings` (returns the gold evidence) and `Calculate`; up "
        f"to {MAX_STEPS} model turns. Valid = known tool name and schema-valid arguments. A "
        "Groq `tool_use_failed` error, or answering without any tool call, counts as one "
        "invalid call.",
        "- Structured output: one forced `PilotAnswer` call; valid = parses and every claim "
        "uses the shared `Unit` and `Period` formats.",
        "- Tokens = input + output per call, from the original (uncached) response.",
        "- A request larger than the account's per-minute input-token limit is refused by "
        "Groq (HTTP 413). Those tests are listed as skipped and left out of both rates: they "
        "measure the Groq plan, not the model.",
        "",
        "## Failures",
        "",
    ]
    failures = [
        f"- `{r['financebench_id']}` ({r['company']}): "
        + "; ".join(
            r["invalid_tool_calls"] + ([r["structured_error"]] if r["structured_error"] else [])
        )
        for r in results
        if r["invalid_tool_calls"] or r["structured_error"]
    ]
    lines += failures or ["None."]
    skipped = [
        f"- `{r['financebench_id']}` ({r['company']}): "
        + ", ".join(
            t
            for t, k in [
                ("tool test", "tool_too_large"),
                ("structured test", "structured_too_large"),
            ]
            if r.get(k)
        )
        for r in results
        if r.get("tool_too_large") or r.get("structured_too_large")
    ]
    lines += ["", "## Skipped (request too large for the Groq plan)", ""] + (skipped or ["None."])
    return "\n".join(lines) + "\n"


def _short_commit() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "nocommit"


def main() -> int:
    selection = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    if selection.get("status") != "approved":
        print(
            f'{QUESTIONS.name} is not approved yet: review the list, then set "status": "approved".'
        )
        return 1
    records = financebench.by_id(financebench.load(financebench.download()))
    cfg = load_config(BASE_CONFIG)
    llm = LLM(cfg)
    date = dt.date.today().isoformat()
    run_id = f"{date}_pilot_{_short_commit()}"
    out_dir = ROOT / "runs" / "pilot" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, q in enumerate(selection["questions"], 1):
        record = records[q["financebench_id"]]
        result = {
            "financebench_id": q["financebench_id"],
            "company": record["company"],
            **tool_test(llm, record, run_id),
            **structured_test(llm, record, run_id),
        }
        results.append(result)
        tools = (
            "tool test SKIPPED (too large)"
            if result["tool_too_large"]
            else f"{len(result['invalid_tool_calls'])} invalid tool calls"
        )
        structured = (
            "SKIPPED (too large)"
            if result["structured_too_large"]
            else "ok"
            if result["structured_valid"]
            else "INVALID"
        )
        print(
            f"[{i}/{len(selection['questions'])}] {q['financebench_id']}: {tools}, "
            f"structured {structured}"
        )
    llm.tracer.flush()

    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    summary = summarize(results)
    meta = {
        "run_id": run_id,
        "date": date,
        "model_id": cfg.model.id,
        "thinking": cfg.model.thinking,
        "temperature": cfg.model.temperature,
    }
    REPORT.write_text(render_report(summary, results, meta), encoding="utf-8")
    print(
        f"\nTool calls {_pct(summary['valid_tool_calls'], summary['tool_calls'])}; "
        f"structured {_pct(summary['structured_valid'], summary['questions'])}. "
        f"Report: {REPORT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
