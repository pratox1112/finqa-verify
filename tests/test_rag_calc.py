"""R0+calc (ROADMAP P3.9): single-shot retrieval, then the model's arithmetic through calculate,
with a fake chat model and a fake embedder. No network."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from test_agent import Recording, ai, text_reply, with_steps
from test_generators import CHUNKS, bad_request, capex_answer, config, ctx, question
from test_index import FakeEmbedder

from finqa.config import Config
from finqa.generators.common import PROMPTS_DIR
from finqa.generators.rag import RagGenerator
from finqa.ingestion.index import add_chunks, open_collection
from finqa.llm import LLM
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

ITEM8_FY2018 = CHUNKS[0].chunk_id
CALC = ("calculate", {"expression": "capex * 1000000", "variables": {"capex": 1577}})


@pytest.fixture
def search(tmp_path: Path) -> FilingSearch:
    collection = open_collection("fake-model", tmp_path / "chroma")
    add_chunks(collection, CHUNKS, FakeEmbedder())
    return FilingSearch(collection, FakeEmbedder(), top_k=5)


def make(
    tmp_path: Path, search: FilingSearch, *replies: Any, cfg: Config | None = None
) -> tuple[RagGenerator, Recording]:
    cfg = cfg or config("ablations/r0_calc_v0.yaml")
    chat = Recording(*replies)
    llm = LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=lambda _: None)
    generator = RagGenerator(
        cfg, llm, CompanyResolver.from_csv(), search, traces_root=tmp_path / "runs"
    )
    return generator, chat


def tool_texts(chat: Recording) -> list[str]:
    return [str(m.content) for m in chat.seen[-1] if isinstance(m, ToolMessage)]


def bound_tools(chat: Recording) -> list[str]:
    assert chat.bound is not None
    return [t["function"]["name"] if isinstance(t, dict) else t.__name__ for t in chat.bound[0]]


def trace(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "runs/run1/agent_traces/q1.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- Config and prompt --------------------------------------------------------------------------


def test_config_is_rag_with_the_calculator_and_no_verification() -> None:
    cfg = config("ablations/r0_calc_v0.yaml")
    assert cfg.name == "r0_calc_v0"
    assert cfg.retrieval.arm == "rag" and cfg.retrieval.calculator
    assert cfg.verification.arm == "none"
    r0 = config("grid/r0_v0.yaml")
    assert cfg.retrieval.model_copy(update={"calculator": False}) == r0.retrieval
    assert cfg.model == r0.model


def test_prompt_is_r0s_plus_the_calculator_rule() -> None:
    r0 = (PROMPTS_DIR / "r0_system.txt").read_text(encoding="utf-8").splitlines()
    calc = (PROMPTS_DIR / "r0_calc_system.txt").read_text(encoding="utf-8").splitlines()
    # one rule and its blank line, after the first paragraph; everything else is R0's
    assert calc[:2] == r0[:2] and calc[3] == "" and calc[4:] == r0[2:]
    rule = calc[2]
    assert "calculate" in rule and "starts with a letter" in rule and "Answer" in rule
    assert "calculate" not in "\n".join(r0)


# --- The calculator loop ------------------------------------------------------------------------


def test_one_calculation_then_answer(tmp_path: Path, search: FilingSearch) -> None:
    replies = [ai(CALC), ai(("Answer", capex_answer([ITEM8_FY2018])), tokens=(300, 50))]
    generator, chat = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.retrieval_arm == "rag"
    assert d.claims[0].value == 1577000000 and d.answer_claim_id == "c1"
    assert ITEM8_FY2018 in d.evidence  # the single search's excerpts are the evidence
    assert (d.tokens_in, d.tokens_out) == (400, 60)  # both calls counted
    assert tool_texts(chat) == ["capex * 1000000 = 1577000000.0"]
    assert bound_tools(chat) == ["calculate", "Answer"]
    assert chat.choices == [None, None]  # the model chooses; nothing is forced
    assert f"[{ITEM8_FY2018}]" in str(chat.seen[0][1].content)  # excerpts in the user turn
    assert "calculate" in str(chat.seen[0][0].content)  # the R0+calc system prompt


def test_several_calculations_before_answering(tmp_path: Path, search: FilingSearch) -> None:
    replies = [
        ai(CALC),
        ai(("calculate", {"expression": "a / b * 100", "variables": {"a": 1577, "b": 1373}})),
        ai(CALC, ("calculate", {"expression": "x + 1", "variables": {"x": 1}})),  # two in one
        ai(("Answer", capex_answer([ITEM8_FY2018]))),
    ]
    generator, chat = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error is None and chat.calls == 4
    assert len(tool_texts(chat)) == 4
    assert tool_texts(chat)[3] == "x + 1 = 2.0"
    assert trace(tmp_path)["steps_used"] == 3


def test_answer_without_calculating(tmp_path: Path, search: FilingSearch) -> None:
    generator, chat = make(tmp_path, search, ai(("Answer", capex_answer([ITEM8_FY2018]))))
    d = generator(question(), ctx("run1"))
    assert d.error is None and chat.calls == 1
    assert trace(tmp_path)["steps_used"] == 0


@pytest.mark.parametrize(
    "call, expected",
    [
        (("calculate", {"expression": "__import__('os')", "variables": {}}), "Error"),
        (("calculate", {"expression": "a / 0", "variables": {"a": 1}}), "division by zero"),
        (("calculate", {"expression": "1 + 1", "variables": {"1": 5}}), "Error"),
        (("calculate", {"variables": {"a": 1}}), "ValidationError"),
        (("search_filings", {"cik": "0000066740", "query": "capex"}), "unknown tool"),
    ],
)
def test_bad_calls_are_reported_to_the_model(
    tmp_path: Path, search: FilingSearch, call: tuple[str, dict[str, Any]], expected: str
) -> None:
    replies = [ai(call), ai(("Answer", capex_answer([ITEM8_FY2018])))]
    generator, chat = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error is None  # the question goes on
    assert expected in tool_texts(chat)[0] and tool_texts(chat)[0].startswith("Error")


def test_no_second_search(tmp_path: Path, search: FilingSearch) -> None:
    replies = [
        ai(("search_filings", {"cik": "0000066740", "query": "capex"})),
        ai(("Answer", capex_answer([ITEM8_FY2018]))),
    ]
    generator, _ = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    first_search = generator.retrieve("3M", question().question)
    assert set(d.evidence) == {c.chunk_id for c in first_search}


# --- Limits and failures ------------------------------------------------------------------------


def test_round_limit_forces_an_answer(tmp_path: Path, search: FilingSearch) -> None:
    cfg = with_steps(config("ablations/r0_calc_v0.yaml"), 2)
    replies = [ai(CALC), ai(CALC), ai(("Answer", capex_answer([ITEM8_FY2018])))]
    generator, chat = make(tmp_path, search, *replies, cfg=cfg)
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.claims
    assert chat.choices == [None, None, "Answer"]
    assert "Stop using tools" in str(chat.seen[-1][-1].content)
    t = trace(tmp_path)
    assert t["steps_used"] == 2 and t["max_steps"] == 2
    assert t["messages"][-1]["type"] == "human"  # the nudge, as in R1's traces


def test_text_reply_is_asked_again(tmp_path: Path, search: FilingSearch) -> None:
    replies = [text_reply("The capex was $1,577 million."), ai(("Answer", capex_answer([])))]
    generator, chat = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.claims[0].value == 1577000000
    assert chat.choices == [None, "Answer"]


def test_trace_records_the_conversation(tmp_path: Path, search: FilingSearch) -> None:
    replies = [ai(CALC), ai(("Answer", capex_answer([ITEM8_FY2018])))]
    generator, _ = make(tmp_path, search, *replies)
    generator(question(), ctx("run1"))
    t = trace(tmp_path)
    assert t["question_id"] == "q1" and t["error"] is None and t["steps_used"] == 1
    assert [m["type"] for m in t["messages"]] == ["system", "human", "ai", "tool", "ai"]


@pytest.mark.parametrize(
    "reply, expected",
    [
        (bad_request(), "BadRequestError"),
        (ai(("Answer", {**capex_answer([]), "claims": [{"claim_id": "c1"}]})), "ValidationError"),
    ],
)
def test_failures_are_drafts_with_an_error(
    tmp_path: Path, search: FilingSearch, reply: Any, expected: str
) -> None:
    generator, _ = make(tmp_path, search, reply)
    d = generator(question(), ctx("run1"))
    assert d.error is not None and d.error.startswith(expected)
    assert d.claims == [] and trace(tmp_path)["error"] == d.error


def test_connection_failure_is_raised(tmp_path: Path, search: FilingSearch) -> None:
    generator, _ = make(tmp_path, search, ConnectionError("down"))
    with pytest.raises(ConnectionError):
        generator(question(), ctx("run1"))


def test_rerun_replays_from_the_cache(tmp_path: Path, search: FilingSearch) -> None:
    replies = [ai(CALC), ai(("Answer", capex_answer([ITEM8_FY2018])))]
    generator, chat = make(tmp_path, search, *replies)
    first = generator(question(), ctx("run1"))
    second = generator(question(), ctx("run1"))
    assert chat.calls == 2  # the second run made no model calls
    assert second.claims == first.claims


# --- R0 itself is unchanged ---------------------------------------------------------------------


def test_r0_still_makes_one_forced_answer_call(tmp_path: Path, search: FilingSearch) -> None:
    generator, chat = make(
        tmp_path,
        search,
        ai(("Answer", capex_answer([ITEM8_FY2018]))),
        cfg=config("grid/r0_v0.yaml"),
    )
    d = generator(question(), ctx("run1"))
    assert d.error is None
    assert chat.choices == ["Answer"] and bound_tools(chat) == ["Answer"]
    assert "calculate" not in str(chat.seen[0][0].content)
    assert not (tmp_path / "runs").exists()  # R0 saves no conversation trace
