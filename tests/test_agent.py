"""Agent generator (R1, and R1-calc without the calculator) with a fake chat model and a fake
embedder. No network."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_generators import CHUNKS, MMM, bad_request, capex_answer, config, ctx, question
from test_index import FakeEmbedder
from test_llm import FakeChat

from finqa.config import Config
from finqa.generators import agent
from finqa.generators.agent import TOOLS, AgentGenerator, section_filter, tool_names, tool_spec
from finqa.generators.common import PROMPTS_DIR
from finqa.ingestion.index import add_chunks, open_collection
from finqa.llm import LLM
from finqa.schemas import Draft
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

ITEM8_FY2018 = CHUNKS[0].chunk_id
SEARCH_ARGS = {"cik": MMM, "query": "capital expenditures", "fiscal_year": 2018, "form": "10-K"}


def ai(*calls: tuple[str, dict[str, Any]], tokens: tuple[int, int] = (100, 10)) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": a, "id": f"call_{i}"} for i, (n, a) in enumerate(calls)],
        usage_metadata={
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "total_tokens": sum(tokens),
        },
    )


def text_reply(text: str) -> AIMessage:
    return AIMessage(
        content=text, usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}
    )


class Recording(FakeChat):
    """Also keeps every message list and tool choice the model was given."""

    def __init__(self, *items: Any) -> None:
        super().__init__(*items)
        self.seen: list[list[Any]] = []
        self.choices: list[Any] = []

    def invoke(self, messages: Any) -> Any:
        self.seen.append(list(messages))
        self.choices.append(self.bound[1] if self.bound else None)
        return super().invoke(messages)


@pytest.fixture
def search(tmp_path: Path) -> FilingSearch:
    collection = open_collection("fake-model", tmp_path / "chroma")
    add_chunks(collection, CHUNKS, FakeEmbedder())
    return FilingSearch(collection, FakeEmbedder(), top_k=5)


def with_steps(cfg: Config, steps: int) -> Config:
    return cfg.model_copy(
        update={"retrieval": cfg.retrieval.model_copy(update={"max_agent_steps": steps})}
    )


def make(
    tmp_path: Path,
    search: FilingSearch,
    *replies: Any,
    cfg: Config | None = None,
    chat: FakeChat | None = None,
) -> tuple[AgentGenerator, FakeChat]:
    cfg = cfg or config("grid/r1_v0.yaml")
    chat = chat or Recording(*replies)
    llm = LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=lambda _: None)
    generator = AgentGenerator(
        cfg, llm, CompanyResolver.from_csv(), search, traces_root=tmp_path / "runs"
    )
    return generator, chat


def full_run() -> list[AIMessage]:
    """resolve -> search -> calculate -> Answer."""
    return [
        ai(("resolve_company", {"name": "3M"})),
        ai(("search_filings", SEARCH_ARGS)),
        ai(("calculate", {"expression": "a * 1000000", "variables": {"a": 1577}})),
        ai(("Answer", capex_answer([ITEM8_FY2018])), tokens=(300, 50)),
    ]


# --- Tools and prompts --------------------------------------------------------------------------


def test_r1_has_every_tool_and_r1_minus_calc_has_no_calculator() -> None:
    assert tool_names(True) == ["resolve_company", "search_filings", "fetch_filing", "calculate"]
    assert tool_names(False) == ["resolve_company", "search_filings", "fetch_filing"]
    assert config("grid/r1_v0.yaml").retrieval.calculator
    nocalc = config("ablations/r1_nocalc_v0.yaml")
    assert nocalc.retrieval.arm == "agentic" and not nocalc.retrieval.calculator


@pytest.mark.parametrize("name", list(TOOLS))
def test_tool_specs_are_function_definitions(name: str) -> None:
    spec = tool_spec(name)
    assert spec["type"] == "function"
    assert spec["function"]["name"] == name
    assert spec["function"]["parameters"]["type"] == "object"
    assert "title" not in spec["function"]["parameters"]


def test_prompts_differ_only_in_the_arithmetic_rule() -> None:
    calc = (PROMPTS_DIR / "r1_system.txt").read_text(encoding="utf-8").splitlines()
    nocalc = (PROMPTS_DIR / "r1_nocalc_system.txt").read_text(encoding="utf-8").splitlines()
    differ = [(a, b) for a, b in zip(calc, nocalc, strict=True) if a != b]
    assert len(differ) == 1
    assert "calculate" in differ[0][0] and "calculate" not in differ[0][1]
    assert (PROMPTS_DIR / "r1_user.txt").exists() and (PROMPTS_DIR / "r1_finalize.txt").exists()


def test_r0_and_r1_give_the_same_answer_form_instructions() -> None:
    def form(name: str) -> str:
        text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
        return text[text.index("Fill in the Answer form:") :]

    assert form("r1_system.txt") == form("r0_system.txt")


def test_agent_rejects_other_arms(tmp_path: Path, search: FilingSearch) -> None:
    cfg = config("grid/r0_v0.yaml")
    llm = LLM(cfg, FakeChat(), cache_dir=tmp_path / "cache")
    with pytest.raises(ValueError, match="not the agent"):
        AgentGenerator(cfg, llm, CompanyResolver.from_csv(), search)


# --- The loop -----------------------------------------------------------------------------------


def test_full_loop_drafts_with_every_retrieved_chunk_as_evidence(
    tmp_path: Path, search: FilingSearch
) -> None:
    generator, chat = make(tmp_path, search, *full_run())
    d = generator(question(), ctx("run1"))
    assert isinstance(d, Draft) and d.error is None
    assert d.retrieval_arm == "agentic"
    assert d.answer_claim_id == "c1" and d.claims[0].chunk_ids == [ITEM8_FY2018]
    retrieved = search.search_filings(MMM, 2018, None, "capital expenditures", form="10-K")
    assert {c.chunk_id for c in retrieved} == set(d.evidence)
    assert ITEM8_FY2018 in d.evidence
    assert all(c.cik == MMM and c.fiscal_year == 2018 for c in d.evidence.values())
    assert (d.tokens_in, d.tokens_out) == (100 * 3 + 300, 10 * 3 + 50)
    assert chat.calls == 4


def test_tool_results_go_back_to_the_model(tmp_path: Path, search: FilingSearch) -> None:
    generator, chat = make(tmp_path, search, *full_run())
    generator(question(), ctx("run1"))
    assert isinstance(chat, Recording)
    tool_texts = [m.content for m in chat.seen[-1] if isinstance(m, ToolMessage)]
    assert "CIK 0000066740" in tool_texts[0]
    assert f"[{ITEM8_FY2018}]" in tool_texts[1] and "table in millions" in tool_texts[1]
    assert tool_texts[2] == "a * 1000000 = 1577000000.0"


def test_trace_is_saved_per_question(tmp_path: Path, search: FilingSearch) -> None:
    generator, _ = make(tmp_path, search, *full_run())
    generator(question(), ctx("run1"))
    trace = json.loads((tmp_path / "runs/run1/agent_traces/q1.json").read_text(encoding="utf-8"))
    assert trace["question_id"] == "q1" and trace["steps_used"] == 3
    assert [m["type"] for m in trace["messages"]][:3] == ["system", "human", "ai"]


def test_step_limit_forces_an_answer(tmp_path: Path, search: FilingSearch) -> None:
    cfg = with_steps(config("grid/r1_v0.yaml"), 2)
    replies = [
        ai(("search_filings", SEARCH_ARGS)),
        ai(("search_filings", {**SEARCH_ARGS, "query": "property plant equipment"})),
        ai(("Answer", capex_answer([ITEM8_FY2018]))),  # the forced call
    ]
    generator, chat = make(tmp_path, search, *replies, cfg=cfg)
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.claims
    assert isinstance(chat, Recording)
    assert chat.choices == [None, None, "Answer"]
    assert "Stop using tools" in str(chat.seen[-1][-1].content)


def test_text_reply_without_answer_is_asked_again(tmp_path: Path, search: FilingSearch) -> None:
    replies = [text_reply("The capex was $1,577 million."), ai(("Answer", capex_answer([])))]
    generator, chat = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.claims[0].value == 1577000000
    assert isinstance(chat, Recording) and chat.choices[-1] == "Answer"


def test_invalid_answer_is_an_error_but_keeps_the_evidence(
    tmp_path: Path, search: FilingSearch
) -> None:
    bad = capex_answer([ITEM8_FY2018])
    bad["claims"][0]["unit"] = "stores"
    replies = [ai(("search_filings", SEARCH_ARGS)), ai(("Answer", bad))]
    generator, _ = make(tmp_path, search, *replies)
    d = generator(question(), ctx("run1"))
    assert d.error and "ValidationError" in d.error
    assert d.claims == [] and ITEM8_FY2018 in d.evidence


def test_refused_request_is_an_error_draft(tmp_path: Path, search: FilingSearch) -> None:
    generator, _ = make(tmp_path, search, ai(("search_filings", SEARCH_ARGS)), bad_request())
    d = generator(question(), ctx("run1"))
    assert d.error and "BadRequestError" in d.error
    assert ITEM8_FY2018 in d.evidence


def test_connection_failure_is_raised_not_scored(tmp_path: Path, search: FilingSearch) -> None:
    generator, _ = make(tmp_path, search, ConnectionError("down"))
    with pytest.raises(ConnectionError):
        generator(question(), ctx("run1"))


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (("lookup", {"x": 1}), "unknown tool 'lookup'"),
        (("search_filings", {"query": "capex"}), "ValidationError"),
        (("search_filings", {"cik": "3M", "query": "capex"}), "'3M' is not a CIK"),
        (("search_filings", {"cik": "66740", "query": "capex"}), "10-digit CIK"),
        (("calculate", {"expression": "__import__('os')", "variables": {}}), "Error"),
        (("calculate", {"expression": "a / 0", "variables": {"a": 1}}), "division by zero"),
    ],
)
def test_bad_tool_calls_are_reported_to_the_model(
    tmp_path: Path, search: FilingSearch, call: tuple[str, dict[str, Any]], expected: str
) -> None:
    generator, chat = make(tmp_path, search, ai(call), ai(("Answer", capex_answer([]))))
    d = generator(question(), ctx("run1"))
    assert d.error is None
    assert isinstance(chat, Recording)
    tool_text = next(m.content for m in chat.seen[-1] if isinstance(m, ToolMessage))
    assert expected in tool_text


@pytest.mark.parametrize(
    ("section", "form", "period", "expected"),
    [
        ("Item 1", "10-Q", None, "Part I, Item 1"),
        ("Item 2", None, "Q2 FY2023", "Part I, Item 2"),
        ("Item 1A", "10-Q", None, "Part II, Item 1A"),
        ("Part I, Item 1", "10-Q", None, "Part I, Item 1"),
        ("Item 1", "10-K", None, "Item 1"),
        ("Item 8", None, "FY2022", "Item 8"),
        ("Item 8", None, None, "Item 8"),
        (None, "10-Q", None, None),
    ],
)
def test_10q_sections_get_their_part(
    section: str | None, form: str | None, period: str | None, expected: str | None
) -> None:
    assert section_filter(section, form, period) == expected


def test_10q_search_with_a_bare_item_finds_part_i(tmp_path: Path, search: FilingSearch) -> None:
    args = {"cik": MMM, "query": "capital expenditure", "form": "10-Q", "section": "Item 1"}
    replies = [ai(("search_filings", args)), ai(("Answer", capex_answer([])))]
    generator, chat = make(tmp_path, search, *replies)
    generator(question(), ctx("run1"))
    assert isinstance(chat, Recording)
    tool_text = next(m.content for m in chat.seen[-1] if isinstance(m, ToolMessage))
    assert CHUNKS[3].chunk_id in tool_text


def test_r1_prompts_ask_for_the_cik_as_returned_and_named_variables() -> None:
    for name in ("r1_system.txt", "r1_nocalc_system.txt"):
        text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
        assert "10-digit CIK" in text and "Part I, Item 1" in text and "already indexed" in text
    calc = (PROMPTS_DIR / "r1_system.txt").read_text(encoding="utf-8")
    assert "starts with a letter" in calc


def test_r1_minus_calc_cannot_call_the_calculator(tmp_path: Path, search: FilingSearch) -> None:
    cfg = config("ablations/r1_nocalc_v0.yaml")
    replies = [
        ai(("calculate", {"expression": "1 + 1", "variables": {}})),
        ai(("Answer", capex_answer([]))),
    ]
    generator, chat = make(tmp_path, search, *replies, cfg=cfg)
    generator(question(), ctx("run1"))
    assert isinstance(chat, Recording)
    tool_text = next(m.content for m in chat.seen[-1] if isinstance(m, ToolMessage))
    assert "unknown tool 'calculate'" in tool_text
    assert "calculate" not in str(chat.seen[0][0].content)  # the system prompt
    assert chat.bound is not None
    assert "calculate" not in [t["function"]["name"] for t in chat.bound[0] if isinstance(t, dict)]


def test_repeated_tool_call_is_served_from_the_tool_cache(
    tmp_path: Path, search: FilingSearch, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    original = search.search_filings

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(search, "search_filings", counting)
    replies = [
        ai(("search_filings", SEARCH_ARGS)),
        ai(("search_filings", SEARCH_ARGS)),
        ai(("Answer", capex_answer([ITEM8_FY2018]))),
    ]
    generator, _ = make(tmp_path, search, *replies)
    generator(question(), ctx("run1"))
    assert len(calls) == 1


def test_fetch_without_a_fetcher_is_reported(tmp_path: Path, search: FilingSearch) -> None:
    replies = [
        ai(("fetch_filing", {"cik": MMM, "form": "10-K", "fiscal_year": 2015})),
        ai(("Answer", capex_answer([]))),
    ]
    generator, chat = make(tmp_path, search, *replies)
    generator(question(), ctx("run1"))
    assert isinstance(chat, Recording)
    tool_text = next(m.content for m in chat.seen[-1] if isinstance(m, ToolMessage))
    assert "not available" in tool_text


def test_rerun_replays_from_the_cache(tmp_path: Path, search: FilingSearch) -> None:
    first, _ = make(tmp_path, search, *full_run())
    d1 = first(question(), ctx("run1"))
    second, chat = make(tmp_path, search, chat=FakeChat())  # no replies left: cache only
    d2 = second(question(), ctx("run2"))
    assert chat.calls == 0
    assert d2.claims == d1.claims and set(d2.evidence) == set(d1.evidence)


def test_module_generate_matches_the_runner_interface() -> None:
    import inspect

    assert list(inspect.signature(agent.generate).parameters) == ["question", "cfg", "ctx"]
