"""Closed-book (S0) and single-shot RAG (R0) generators with a fake chat model and a fake
embedder. No network."""

from pathlib import Path
from typing import Any

import groq
import httpx
import pytest
from langchain_core.messages import AIMessage
from test_index import FakeEmbedder
from test_llm import FakeChat

from finqa.config import CONFIGS_DIR, Config, load_config
from finqa.generators.base import Question, RunContext
from finqa.generators.closed_book import ClosedBookGenerator
from finqa.generators.common import PROMPTS_DIR, Answer, messages
from finqa.generators.rag import (
    Filters,
    RagGenerator,
    excerpt,
    question_filters,
    relaxations,
)
from finqa.ingestion.index import add_chunks, open_collection
from finqa.llm import LLM
from finqa.schemas import Chunk, Draft
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch
from finqa.tracing import trace_id_for

MMM = "0000066740"
QUESTION = "What is 3M's FY2018 capital expenditure in USD millions?"


def question(company: str = "3M", text: str = QUESTION) -> Question:
    return Question("q1", company, text, "3M_2018_10K", "10k", 2018, "single_fact")


def ctx(run_id: str = "run1") -> RunContext:
    return RunContext(run_id, f"{run_id}:q1", trace_id_for(run_id, "q1"))


def tool_reply(args: dict[str, Any] | None, tokens: tuple[int, int] = (900, 120)) -> AIMessage:
    calls = [{"name": "Answer", "args": args, "id": "call_1"}] if args is not None else []
    return AIMessage(
        content="",
        tool_calls=calls,
        usage_metadata={
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "total_tokens": sum(tokens),
        },
    )


def capex_answer(chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "answer_text": "3M's FY2018 capital expenditure was $1,577 million.",
        "claims": [
            {
                "claim_id": "c1",
                "metric": "capital expenditures",
                "value": 1577000000,
                "unit": "USD",
                "period": "FY2018",
                "chunk_ids": chunk_ids,
            }
        ],
        "answer_claim_id": "c1",
    }


def chunk(cik: str, year: int, form: str, period: str, section: str, text: str) -> Chunk:
    accession = f"{cik}-{form}-{period.replace(' ', '')}"
    return Chunk(
        chunk_id=f"{accession}-{section.lower().replace(' ', '-')}",
        cik=cik,
        ticker="MMM" if cik == MMM else "KO",
        form=form,
        fiscal_year=year,
        period=period,
        section=section,
        is_table=section == "Item 8",
        unit_scale=1e6 if section == "Item 8" else None,
        text=text,
        source_accession=accession,
    )


CHUNKS = [
    chunk(MMM, 2018, "10-K", "FY2018", "Item 8", "purchases of property plant equipment 1,577"),
    chunk(MMM, 2018, "10-K", "FY2018", "Item 7", "capital expenditure outlook"),
    chunk(MMM, 2017, "10-K", "FY2017", "Item 8", "purchases of property plant equipment 1,373"),
    chunk(MMM, 2019, "10-Q", "Q2 FY2019", "Part I, Item 1", "quarter capital expenditure"),
    chunk("0000021344", 2018, "10-K", "FY2018", "Item 8", "capital expenditure 1,347"),
]


def config(name: str) -> Config:
    return load_config(CONFIGS_DIR / name)


def make_llm(cfg: Config, chat: FakeChat, tmp_path: Path) -> LLM:
    return LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=lambda _: None)


@pytest.fixture
def search(tmp_path: Path) -> FilingSearch:
    collection = open_collection("fake-model", tmp_path / "chroma")
    add_chunks(collection, CHUNKS, FakeEmbedder())
    return FilingSearch(collection, FakeEmbedder(), top_k=5)


def rag(tmp_path: Path, search: FilingSearch, *replies: Any) -> tuple[RagGenerator, FakeChat]:
    cfg = config("grid/r0_v0.yaml")
    chat = FakeChat(*replies)
    generator = RagGenerator(cfg, make_llm(cfg, chat, tmp_path), CompanyResolver.from_csv(), search)
    return generator, chat


# --- Prompts --------------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ["s0", "r0"])
def test_prompt_files_exist_and_fill(arm: str) -> None:
    fields = {"company": "3M", "question": "Q?", "excerpts": "[id] text"}
    system, user = messages(f"{arm}_system.txt", f"{arm}_user.txt", **fields)
    assert "$1.2 billion" in str(system.content)  # system prompts are used as written
    assert "Company: 3M\nQuestion: Q?" in str(user.content)


def test_answer_form_is_the_shared_claim_schema() -> None:
    claim = Answer.model_json_schema()["$defs"]["Claim"]
    assert {"claim_id", "value", "unit", "period", "chunk_ids"} <= claim["properties"].keys()
    assert (PROMPTS_DIR / "FROZEN.txt").exists()


# --- S0 -------------------------------------------------------------------------------------


def test_closed_book_produces_a_valid_draft_with_no_evidence(tmp_path: Path) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    chat = FakeChat(tool_reply(capex_answer([])))
    d = ClosedBookGenerator(cfg, make_llm(cfg, chat, tmp_path))(question(), ctx("run1"))
    assert isinstance(d, Draft) and d.error is None
    assert d.retrieval_arm == "closed_book" and d.evidence == {}
    assert d.claims[0].value == 1577000000 and d.answer_claim_id == "c1"
    assert (d.tokens_in, d.tokens_out) == (900, 120) and d.trace_id == ctx().trace_id
    tools, choice = chat.bound  # type: ignore[misc]
    assert tools == [Answer] and choice == "Answer"


def test_closed_book_cache_hit_keeps_token_counts(tmp_path: Path) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    generator = ClosedBookGenerator(
        cfg, make_llm(cfg, FakeChat(tool_reply(capex_answer([]))), tmp_path)
    )
    first = generator(question(), ctx("run1"))
    again = generator(question(), ctx("run2"))
    assert again.claims == first.claims and again.tokens_in == 900


def test_closed_book_rejects_another_arm(tmp_path: Path) -> None:
    cfg = config("grid/r0_v0.yaml")
    with pytest.raises(ValueError):
        ClosedBookGenerator(cfg, make_llm(cfg, FakeChat(), tmp_path))


# --- Failures become drafts with an error ---------------------------------------------------


def bad_request() -> groq.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
    return groq.BadRequestError("tool_use_failed", response=response, body=None)


@pytest.mark.parametrize(
    "reply, expected",
    [
        (tool_reply(None), "StructuredOutputError"),
        (tool_reply({**capex_answer([]), "claims": [{"claim_id": "c1"}]}), "ValidationError"),
        (bad_request(), "BadRequestError"),
    ],
)
def test_failed_generation_is_a_draft_with_error(tmp_path: Path, reply: Any, expected: str) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    d = ClosedBookGenerator(cfg, make_llm(cfg, FakeChat(reply), tmp_path))(question(), ctx("run1"))
    assert d.error is not None and d.error.startswith(expected)
    assert d.claims == [] and d.answer_text == ""


def test_connection_failure_is_raised_not_scored(tmp_path: Path) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    generator = ClosedBookGenerator(cfg, make_llm(cfg, FakeChat(ConnectionError("down")), tmp_path))
    with pytest.raises(ConnectionError):
        generator(question(), ctx("run1"))


# --- R0 filters -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, expected",
    [
        (QUESTION, Filters(2018, "10-K")),
        ("What is the FY2019 - FY2020 total revenue growth rate?", Filters(2020, "10-K")),
        ("What are the major products AMD sells as of FY22?", Filters(2022, "10-K")),
        ("Quick ratio for FY 2022?", Filters(2022, "10-K")),
        ("Quick ratio for Q2 of FY2023?", Filters(2023, "10-Q", "Q2 FY2023")),
        ("Any drop between FY 2023 and Q2 of FY2024?", Filters(2024, "10-Q", "Q2 FY2024")),
        ("If JPM went bankrupt by the end of 2021 Q1?", Filters(2021, "10-Q", "Q1 FY2021")),
        ("Third quarter 2019 revenue?", Filters(2019, "10-Q", "Q3 FY2019")),
        ("Q4 FY2022 revenue?", Filters(2022, "10-K")),
        ("How much does Pfizer expect to pay to spin off Upjohn?", Filters()),
        ("Revenue of $2,000 million?", Filters()),
    ],
)
def test_question_filters(question: str, expected: Filters) -> None:
    assert question_filters(question) == expected


def test_relaxations_drop_period_then_form_then_year_and_keep_company() -> None:
    steps = relaxations(MMM, Filters(2019, "10-Q", "Q2 FY2019"))
    assert [tuple(s.values()) for s in steps] == [
        (MMM, 2019, "10-Q", "Q2 FY2019"),
        (MMM, 2019, "10-Q", None),
        (MMM, 2019, None, None),
        (MMM, None, None, None),
    ]
    assert len(relaxations(MMM, Filters())) == 1


def test_excerpt_header_states_id_filing_section_and_scale() -> None:
    table, text = CHUNKS[0], CHUNKS[1]
    assert excerpt(table, "3M").split("\n")[0] == (
        f"[{table.chunk_id}] 3M 10-K FY2018, Item 8, table in millions"
    )
    assert excerpt(text, "3M").split("\n")[0].endswith("FY2018, Item 7")
    unscaled = table.model_copy(update={"unit_scale": None})
    assert excerpt(unscaled, "3M").split("\n")[0].endswith("table (scale not stated)")


# --- R0 -------------------------------------------------------------------------------------


def test_rag_retrieves_only_the_questions_filing_and_cites_it(
    tmp_path: Path, search: FilingSearch
) -> None:
    cited = CHUNKS[0].chunk_id
    generator, chat = rag(tmp_path, search, tool_reply(capex_answer([cited])))
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.retrieval_arm == "rag"
    assert set(d.evidence) == {CHUNKS[0].chunk_id, CHUNKS[1].chunk_id}  # 3M FY2018 10-K only
    assert d.claims[0].chunk_ids == [cited] and cited in d.evidence


def test_rag_prompt_contains_the_excerpts(tmp_path: Path, search: FilingSearch) -> None:
    seen: list[Any] = []

    class Recording(FakeChat):
        def invoke(self, messages: Any) -> Any:
            seen.extend(messages)
            return super().invoke(messages)

    cfg = config("grid/r0_v0.yaml")
    chat = Recording(tool_reply(capex_answer([CHUNKS[0].chunk_id])))
    RagGenerator(cfg, make_llm(cfg, chat, tmp_path), CompanyResolver.from_csv(), search)(
        question(), ctx("run1")
    )
    user = str(seen[-1].content)
    assert f"[{CHUNKS[0].chunk_id}] 3M 10-K FY2018, Item 8, table in millions" in user
    assert "1,577" in user and "1,347" not in user  # Coca-Cola's chunk is filtered out


def test_rag_relaxes_filters_when_the_filing_is_not_indexed(
    tmp_path: Path, search: FilingSearch
) -> None:
    generator, _ = rag(tmp_path, search)
    hits = generator.retrieve("3M", "Capital expenditure in Q3 FY2019?")  # no Q3 10-Q indexed
    assert [h.period for h in hits] == ["Q2 FY2019"]  # same year and form, period dropped


def test_rag_brand_name_resolves_to_the_company(tmp_path: Path, search: FilingSearch) -> None:
    generator, _ = rag(tmp_path, search)
    assert {h.cik for h in generator.retrieve("Coke", QUESTION)} == {"0000021344"}


def test_rag_with_nothing_retrieved_still_drafts(tmp_path: Path) -> None:
    empty = FilingSearch(open_collection("fake-model", tmp_path / "empty"), FakeEmbedder(), 5)
    generator, _ = rag(tmp_path, empty, tool_reply({**capex_answer([]), "claims": []}))
    d = generator(question(), ctx("run1"))
    assert d.error is None and d.evidence == {} and d.claims == []


def test_rag_rejects_other_arms_and_the_calculator(tmp_path: Path, search: FilingSearch) -> None:
    resolver = CompanyResolver.from_csv()
    s0 = config("baselines/s0_closed_book.yaml")
    with pytest.raises(ValueError):
        RagGenerator(s0, make_llm(s0, FakeChat(), tmp_path), resolver, search)
    calc = s0.model_copy(
        update={"retrieval": s0.retrieval.model_copy(update={"arm": "rag", "calculator": True})}
    )
    with pytest.raises(ValueError, match="R0\\+calc"):
        RagGenerator(calc, make_llm(calc, FakeChat(), tmp_path), resolver, search)


def test_rag_takes_top_k_tables_plus_text_chunks(tmp_path: Path) -> None:
    tables = [
        chunk(MMM, 2018, "10-K", "FY2018", "Item 8", f"capital expenditure table {i}").model_copy(
            update={"chunk_id": f"t{i}"}
        )
        for i in range(7)
    ]
    texts = [
        chunk(MMM, 2018, "10-K", "FY2018", "Item 7", f"capital expenditure text {i}").model_copy(
            update={"chunk_id": f"x{i}"}
        )
        for i in range(3)
    ]
    collection = open_collection("fake-model", tmp_path / "many")
    add_chunks(collection, tables + texts, FakeEmbedder())
    generator, _ = rag(tmp_path, FilingSearch(collection, FakeEmbedder(), top_k=5))
    hits = generator.retrieve("3M", QUESTION)
    r = generator.cfg.retrieval
    assert [h.is_table for h in hits] == [True] * r.top_k + [False] * r.rag_text_chunks


# --- Runner interface -------------------------------------------------------------------


@pytest.mark.parametrize("module", ["closed_book", "rag"])
def test_module_generate_matches_the_runner_interface(module: str) -> None:
    import importlib
    import inspect

    generate = importlib.import_module(f"finqa.generators.{module}").generate
    assert list(inspect.signature(generate).parameters) == ["question", "cfg", "ctx"]


def test_module_generate_builds_once_per_config_and_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finqa.generators import closed_book

    cfg = config("baselines/s0_closed_book.yaml")
    chat = FakeChat(tool_reply(capex_answer([])), tool_reply(capex_answer([])))
    built: list[Config] = []

    def fake_llm(c: Config) -> LLM:
        built.append(c)
        return make_llm(c, chat, tmp_path)

    monkeypatch.setattr(closed_book, "LLM", fake_llm)
    closed_book._generator.cache_clear()
    try:
        first = closed_book.generate(question(), cfg, ctx("run1"))
        second = closed_book.generate(question(text=QUESTION + " "), cfg, ctx("run2"))
    finally:
        closed_book._generator.cache_clear()
    assert len(built) == 1  # one model wrapper for the whole run
    assert first.error is None and second.trace_id == ctx("run2").trace_id


@pytest.mark.parametrize(
    "raw, expected",
    [("c2", "c2"), ("2", "c2"), (" c1 ", "c1"), (None, "c2"), ("null", "c2"), ("c9", "c2")],
)
def test_answer_claim_id_tolerates_model_slips(raw: str | None, expected: str) -> None:
    from finqa.generators.common import answer_claim_id

    two = capex_answer([])
    two["claims"].append({**two["claims"][0], "claim_id": "c2", "metric": "growth", "unit": "%"})
    a = Answer.model_validate({**two, "answer_claim_id": raw})
    assert answer_claim_id(a) == expected


def test_answer_claim_id_is_none_without_claims() -> None:
    from finqa.generators.common import answer_claim_id

    a = Answer.model_validate(
        {"answer_text": "Qualitative.", "claims": [], "answer_claim_id": None}
    )
    assert answer_claim_id(a) is None


# --- Recovering answers Groq's tool parser refused ----------------------------------------

FAILED_GENERATION = (
    "<tool_call>\n<function=Call>\n<parameter=answer_text>\n"
    "Netflix's total current liabilities were $5,466.3 million.\n</parameter>\n"
    '<parameter=claims>\n[{"claim_id": "c1", "metric": "total current liabilities", '
    '"value": 5466312000, "unit": "USD", "period": "FY2017", "chunk_ids": ["nflx-8-52"]}]\n'
    "</parameter>\n<parameter=answer_claim_id>\nc1\n</parameter>\n</function>\n</tool_call>"
)


def tool_use_failed(generation: str, nested: bool = True) -> groq.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
    inner = {"code": "tool_use_failed", "failed_generation": generation}
    return groq.BadRequestError(
        "tool_use_failed", response=response, body={"error": inner} if nested else inner
    )


@pytest.mark.parametrize("nested", [True, False])
def test_answer_refused_by_groqs_parser_is_recovered(tmp_path: Path, nested: bool) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    chat = FakeChat(tool_use_failed(FAILED_GENERATION, nested))
    d = ClosedBookGenerator(cfg, make_llm(cfg, chat, tmp_path))(question(), ctx())
    assert d.error is None and d.answer_claim_id == "c1"
    assert d.claims[0].value == 5466312000 and d.claims[0].chunk_ids == ["nflx-8-52"]


@pytest.mark.parametrize(
    "generation",
    [
        FAILED_GENERATION.replace('"unit": "USD"', '"unit": "dollars"'),  # invalid claim
        FAILED_GENERATION.replace("[{", "[{{"),  # broken JSON
        "<tool_call>\n<function=Answer>\n<parameter=answer_text>\nhi\n</parameter>",  # no claims
    ],
)
def test_unrecoverable_refusal_stays_an_error(tmp_path: Path, generation: str) -> None:
    cfg = config("baselines/s0_closed_book.yaml")
    chat = FakeChat(tool_use_failed(generation))
    d = ClosedBookGenerator(cfg, make_llm(cfg, chat, tmp_path))(question(), ctx())
    assert d.error is not None and d.error.startswith("BadRequestError") and d.claims == []
