"""Pilot and pilot-selection logic, with a fake model. No network."""

from pathlib import Path
from typing import Any

import groq
import httpx
import pytest
from langchain_core.messages import AIMessage
from pilot import (
    NO_NEW_PASSAGES,
    arithmetic,
    render_report,
    run_tool,
    structured_test,
    summarize,
    tool_test,
    validate_tool_call,
)
from select_pilot_questions import QUOTAS, is_numeric_answer, select

from finqa.config import BASE_CONFIG, load_config
from finqa.llm import LLM

RECORD = {  # synthetic, shaped like a FinanceBench record
    "financebench_id": "fb_test_1",
    "company": "ExampleCo",
    "question": "What was ExampleCo's FY2022 capital expenditure in USD millions?",
    "evidence": [{"evidence_text": "Purchases of property, plant and equipment (1,577)"}],
}
USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def ai(content: str = "", tool_calls: list[dict] | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [], usage_metadata=USAGE)


class FakeChat:
    def __init__(self, *items: Any) -> None:
        self.items = list(items)

    def bind_tools(self, tools: Any, tool_choice: Any = None) -> "FakeChat":
        return self

    def invoke(self, messages: Any) -> Any:
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def llm(tmp_path: Path, *items: Any) -> LLM:
    return LLM(load_config(BASE_CONFIG), FakeChat(*items), cache_dir=tmp_path)


SEARCH = {
    "name": "SearchFilings",
    "args": {"company": "ExampleCo", "fiscal_year": 2022, "query": "capex"},
    "id": "t1",
}


def test_arithmetic() -> None:
    assert arithmetic("(a - b) / b * 100", {"a": 110, "b": 100}) == pytest.approx(10.0)
    assert arithmetic("-2 ** 2 + 1.5", {}) == pytest.approx(-2.5)
    for bad in ["__import__('os')", "a.b", "max(1, 2)", "x"]:
        with pytest.raises((ValueError, SyntaxError)):
            arithmetic(bad, {})


def test_validate_tool_call() -> None:
    assert validate_tool_call(SEARCH) is None
    assert (
        validate_tool_call(
            {"name": "Calculate", "args": {"expression": "a+1", "variables": {"a": 1}}}
        )
        is None
    )
    assert "unknown tool" in validate_tool_call({"name": "Search", "args": {}})
    assert "invalid arguments" in validate_tool_call(
        {"name": "SearchFilings", "args": {"company": "X", "fiscal_year": "last year"}}
    )


def test_tool_test_counts_valid_calls(tmp_path: Path) -> None:
    result = tool_test(
        llm(tmp_path, ai(tool_calls=[SEARCH]), ai("Capex was $1,577M.")), RECORD, "run"
    )
    assert result["tool_calls"] == 1 and result["invalid_tool_calls"] == []
    assert result["tool_tokens"] == [120, 120]


def test_tool_test_answer_without_tools_is_a_failure(tmp_path: Path) -> None:
    result = tool_test(llm(tmp_path, ai("Capex was $1,577M.")), RECORD, "run")
    assert result["tool_calls"] == 1
    assert result["invalid_tool_calls"] == ["answered without calling a tool"]


def test_tool_test_groq_tool_use_failed_is_a_failure(tmp_path: Path) -> None:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
    error = groq.BadRequestError("tool_use_failed", response=response, body=None)
    result = tool_test(llm(tmp_path, error), RECORD, "run")
    assert result["tool_calls"] == 1 and result["invalid_tool_calls"][0].startswith("groq error")


def answer_call(args: dict) -> dict:
    return {"name": "PilotAnswer", "args": args, "id": "s1"}


VALID_ANSWER = {
    "answer_text": "Capex was $1,577M.",
    "claims": [
        {"metric": "capital expenditure", "value": 1577000000, "unit": "USD", "period": "FY2022"}
    ],
}


def test_structured_valid(tmp_path: Path) -> None:
    result = structured_test(
        llm(tmp_path, ai(tool_calls=[answer_call(VALID_ANSWER)])), RECORD, "run"
    )
    assert result == {
        "structured_valid": True,
        "structured_error": None,
        "structured_tokens": 120,
        "structured_too_large": False,
    }


@pytest.mark.parametrize("bad", [{"unit": "USD millions"}, {"period": "2022"}])
def test_structured_invalid_formats(tmp_path: Path, bad: dict) -> None:
    args = {**VALID_ANSWER, "claims": [{**VALID_ANSWER["claims"][0], **bad}]}
    result = structured_test(llm(tmp_path, ai(tool_calls=[answer_call(args)])), RECORD, "run")
    assert result["structured_valid"] is False
    assert result["structured_error"].startswith("claims.0.")


def test_summarize_and_report() -> None:
    results = [
        {
            "financebench_id": "a",
            "company": "A",
            "tool_calls": 2,
            "invalid_tool_calls": [],
            "tool_tokens": [100, 300],
            "structured_valid": True,
            "structured_error": None,
            "structured_tokens": 200,
        },
        {
            "financebench_id": "b",
            "company": "B",
            "tool_calls": 2,
            "invalid_tool_calls": ["unknown tool 'x'"],
            "tool_tokens": [100],
            "structured_valid": False,
            "structured_error": "period: bad",
            "structured_tokens": 50,
        },
    ]
    s = summarize(results)
    assert (s["tool_calls"], s["valid_tool_calls"], s["structured_valid"]) == (4, 3, 1)
    assert s["tokens_all"] == {"mean": 150, "max": 300}
    meta = {
        "run_id": "r",
        "date": "2026-10-30",
        "model_id": "m",
        "thinking": "off",
        "temperature": 0,
    }
    report = render_report(s, results, meta)
    assert "3/4, 75.0%" in report and "1/2, 50.0%" in report and "BELOW TARGET" in report
    assert "`b` (B): unknown tool 'x'; period: bad" in report


def test_is_numeric_answer() -> None:
    assert is_numeric_answer("$1577.00")
    assert is_numeric_answer("Margins fell from 36.8% to 34.6%.")
    assert not is_numeric_answer("No, the company is managing capex efficiently.")


def test_select_is_stratified_and_deterministic() -> None:
    records = [
        {
            "financebench_id": f"id_{t[:3]}_{i:02d}",
            "company": f"Co{i % 9}",
            "question_type": t,
            "doc_type": "10k" if i % 5 else "8k",
            "answer": "$1.0" if i % 2 else "Yes.",
        }
        for t in QUOTAS
        for i in range(30)
    ]
    chosen = select(records)
    assert len(chosen) == sum(QUOTAS.values())
    for qtype, n in QUOTAS.items():
        assert sum(r["question_type"] == qtype for r in chosen) == n
    assert all(r["doc_type"] == "10k" for r in chosen)
    assert [r["financebench_id"] for r in select(records)] == [r["financebench_id"] for r in chosen]


def status_error(status: int) -> groq.APIStatusError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com"))
    return groq.APIStatusError("Request too large", response=response, body=None)


def test_too_large_request_is_skipped_not_failed(tmp_path: Path) -> None:
    tool = tool_test(llm(tmp_path, status_error(413)), RECORD, "run")
    assert tool["tool_too_large"] is True and tool["invalid_tool_calls"] == []
    structured = structured_test(llm(tmp_path / "s", status_error(413)), RECORD, "run")
    assert structured["structured_too_large"] is True and structured["structured_error"] is None


def test_repeat_search_returns_short_note() -> None:
    assert run_tool(SEARCH, "EVIDENCE") == "EVIDENCE"
    assert run_tool(SEARCH, "EVIDENCE", searched_before=True) == NO_NEW_PASSAGES


def test_summary_leaves_out_too_large() -> None:
    base = {
        "tool_calls": 1,
        "invalid_tool_calls": [],
        "tool_tokens": [10],
        "structured_valid": True,
        "structured_error": None,
        "structured_tokens": 10,
    }
    results = [
        {
            "financebench_id": "a",
            "company": "A",
            **base,
            "tool_too_large": False,
            "structured_too_large": False,
        },
        {
            "financebench_id": "b",
            "company": "B",
            **base,
            "tool_calls": 0,
            "tool_tokens": [],
            "structured_valid": False,
            "structured_tokens": None,
            "tool_too_large": True,
            "structured_too_large": True,
        },
    ]
    s = summarize(results)
    assert (s["tool_calls"], s["tool_call_rate"]) == (1, 1.0)
    assert (s["structured_questions"], s["structured_rate"]) == (1, 1.0)
    assert (s["tool_too_large"], s["structured_too_large"]) == (1, 1)
    meta = {"run_id": "r", "date": "d", "model_id": "m", "thinking": "off", "temperature": 0}
    report = render_report(s, results, meta)
    assert "`b` (B): tool test, structured test" in report and "PASS" in report
