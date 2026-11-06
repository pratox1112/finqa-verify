"""Filing search tool with a fake embedder in a temporary Chroma. No network."""

from pathlib import Path

import pytest
from test_index import FakeEmbedder

from finqa.ingestion.index import add_chunks, open_collection
from finqa.schemas import Chunk
from finqa.tools.search import FilingSearch

CIKS = ("0000066740", "0000320193")


def chunk(cik: str, year: int, form: str, period: str, section: str, text: str) -> Chunk:
    accession = f"{cik}-{form}-{period.replace(' ', '')}"
    return Chunk(
        chunk_id=f"{accession}-{section.lower().replace(' ', '-').replace(',', '')}",
        cik=cik,
        ticker={"0000066740": "MMM", "0000320193": "AAPL"}[cik],
        form=form,
        fiscal_year=year,
        period=period,
        section=section,
        is_table=True,
        unit_scale=1e6,
        text=f"capital expenditures purchases of property {text}",
        source_accession=accession,
    )


CHUNKS = [
    *(
        chunk(cik, year, "10-K", f"FY{year}", section, f"{cik} {year} {section}")
        for cik in CIKS
        for year in (2018, 2019)
        for section in ("Item 7", "Item 8")
    ),
    chunk(CIKS[0], 2019, "10-Q", "Q2 FY2019", "Part I, Item 1", "quarter two"),
    chunk(CIKS[0], 2019, "10-Q", "Q3 FY2019", "Part I, Item 1", "quarter three"),
]


@pytest.fixture
def tool(tmp_path: Path) -> FilingSearch:
    collection = open_collection("fake-model", tmp_path / "chroma")
    add_chunks(collection, CHUNKS, FakeEmbedder())
    return FilingSearch(collection, FakeEmbedder(), top_k=3)


def test_every_filter_is_respected(tool: FilingSearch) -> None:
    hits = tool.search_filings(CIKS[0], 2018, "Item 8", "capital expenditures", k=50)
    assert [h.chunk_id for h in hits] == [f"{CIKS[0]}-10-K-FY2018-item-8"]


def test_none_filters_are_not_applied(tool: FilingSearch) -> None:
    hits = tool.search_filings(CIKS[1], None, None, "capital expenditures", k=50)
    assert len(hits) == 4 and {h.cik for h in hits} == {CIKS[1]}
    assert len(tool.search_filings(None, None, None, "capital", k=50)) == len(CHUNKS)


def test_form_and_period_select_one_quarter(tool: FilingSearch) -> None:
    hits = tool.search_filings(CIKS[0], 2019, None, "capital", form="10-Q", period="Q3 FY2019")
    assert [(h.form, h.period) for h in hits] == [("10-Q", "Q3 FY2019")]


def test_returns_top_k_chunks_with_ids_nearest_first(tool: FilingSearch) -> None:
    hits = tool.search_filings(CIKS[0], None, None, f"{CIKS[0]} 2019 Item 7")
    assert len(hits) == tool.top_k == 3
    assert hits[0].chunk_id == f"{CIKS[0]}-10-K-FY2019-item-7"
    by_id = {c.chunk_id: c for c in CHUNKS}
    assert all(h == by_id[h.chunk_id] for h in hits)  # the stored chunk, ID and all


def test_no_match_returns_nothing(tool: FilingSearch) -> None:
    assert tool.search_filings(CIKS[0], 2030, None, "capital") == []


def test_rejects_empty_query_and_bad_k(tool: FilingSearch) -> None:
    with pytest.raises(ValueError):
        tool.search_filings(CIKS[0], 2018, None, "  ")
    with pytest.raises(ValueError):
        FilingSearch(tool.collection, tool.embedder, top_k=0)


def test_is_table_selects_tables_or_text(tmp_path: Path) -> None:
    text = CHUNKS[0].model_copy(
        update={"chunk_id": "text-1", "is_table": False, "unit_scale": None}
    )
    collection = open_collection("fake-model", tmp_path / "mixed")
    add_chunks(collection, [CHUNKS[0], text], FakeEmbedder())
    tool = FilingSearch(collection, FakeEmbedder(), top_k=5)
    assert [
        h.chunk_id for h in tool.search_filings(None, None, None, "capital", is_table=False)
    ] == ["text-1"]
    assert all(h.is_table for h in tool.search_filings(None, None, None, "capital", is_table=True))
