"""On-demand fetch tool with fake EDGAR filings, a fake embedder and a temporary Chroma.
No network."""

from pathlib import Path
from typing import Any

import pytest
from test_index import FakeEmbedder

from finqa.config import BASE_CONFIG, load_config
from finqa.ingestion.index import open_collection
from finqa.tools.fetch import FilingFetcher, target_period
from finqa.tools.search import FilingSearch

MMM = "0000066740"
COMPANIES = [{"company": "3M", "cik": MMM, "ticker": "MMM"}]

TEN_K = """# 3M Company annual report

# Item 7. Management's Discussion and Analysis

Sales grew in 2015 as the company expanded capital expenditure programs across all segments.

# Item 8. Financial Statements and Supplementary Data

Consolidated Balance Sheet (Millions)

| | 2015 | 2014 |
|---|---|---|
| Property, plant and equipment, net | 8,515 | 8,489 |
| Total assets | 32,718 | 31,209 |

# Item 9. Changes in and Disagreements with Accountants

None.
"""


class FakeFiling:
    def __init__(self, accession: str, form: str, period_end: str, markdown: str = "") -> None:
        self.accession_no = accession
        self.form = form
        self.period_of_report = period_end
        self.filing_date = period_end
        self.attachments: list[Any] = []
        self._markdown = markdown
        self.downloads = 0

    def obj(self) -> Any:  # structured parsing unavailable: the heading fallback is used
        raise RuntimeError("no structured object in tests")

    def markdown(self) -> str:
        self.downloads += 1
        return self._markdown


TEN_Q = """# Part I. Financial Information

# Item 1. Financial Statements

Consolidated Balance Sheet (Millions)

| | June 30, 2015 | Dec 31, 2014 |
|---|---|---|
| Total assets | 33,102 | 31,209 |

# Item 2. Management's Discussion and Analysis

Second-quarter sales were steady.
"""

FILINGS = [
    FakeFiling("0000066740-16-000001", "10-K", "2015-12-31", TEN_K),
    FakeFiling("0000066740-15-000002", "10-Q", "2015-06-30", TEN_Q),
    FakeFiling("0000066740-15-000003", "10-K", "2014-12-31", TEN_K.replace("2015", "2014")),
]


@pytest.fixture
def fetcher(tmp_path: Path) -> FilingFetcher:
    collection = open_collection("fake-model", tmp_path / "chroma")
    search = FilingSearch(collection, FakeEmbedder(), top_k=5)
    return FilingFetcher(
        search,
        load_config(BASE_CONFIG).chunking,
        list_filings=lambda cik: FILINGS,
        company_facts=lambda cik: {},
        companies=COMPANIES,
        raw_dir=tmp_path / "raw",
        sections_dir=tmp_path / "sections",
        chunks_dir=tmp_path / "chunks",
    )


def test_fetching_an_unindexed_filing_makes_it_searchable(
    fetcher: FilingFetcher, tmp_path: Path
) -> None:
    assert fetcher.search.search_filings(MMM, 2015, "Item 8", "total assets") == []
    result = fetcher.fetch_filing(MMM, "10-K", 2015)
    assert result.status == "fetched" and result.accession == "0000066740-16-000001"
    assert result.period == "FY2015" and result.chunks > 0
    hits = fetcher.search.search_filings(MMM, 2015, "Item 8", "total assets")
    assert hits and all(h.source_accession == result.accession for h in hits)
    assert any(h.is_table and h.unit_scale == 1e6 for h in hits)  # scale read from the caption
    assert (tmp_path / "chunks" / MMM / f"{result.accession}.jsonl").exists()


def test_already_indexed_filing_is_a_no_op(fetcher: FilingFetcher) -> None:
    first = fetcher.fetch_filing(MMM, "10-K", 2015)
    count = fetcher.search.collection.count()
    downloads = FILINGS[0].downloads
    again = fetcher.fetch_filing(MMM, "10-K", 2015)
    assert again.status == "already_indexed" and again.chunks == 0
    assert fetcher.search.collection.count() == count and first.chunks == count
    assert FILINGS[0].downloads == downloads  # nothing downloaded the second time


def test_ten_q_is_found_by_its_fiscal_quarter(fetcher: FilingFetcher) -> None:
    result = fetcher.fetch_filing(MMM, "10-Q", 2015, quarter=2)
    assert result.status == "fetched" and result.accession == "0000066740-15-000002"
    hits = fetcher.search.search_filings(MMM, 2015, None, "total assets", form="10-Q")
    assert hits and {h.period for h in hits} == {"Q2 FY2015"}


def test_missing_filing_is_reported_not_raised(fetcher: FilingFetcher) -> None:
    result = fetcher.fetch_filing(MMM, "10-K", 2009)
    assert result.status == "not_found" and result.accession is None


def test_filing_without_sections_is_reported_empty(tmp_path: Path) -> None:
    blank = FakeFiling("0000066740-17-000009", "10-K", "2016-12-31", "No item headings here.")
    collection = open_collection("fake-model", tmp_path / "chroma")
    fetcher = FilingFetcher(
        FilingSearch(collection, FakeEmbedder(), top_k=5),
        load_config(BASE_CONFIG).chunking,
        list_filings=lambda cik: [blank],
        company_facts=lambda cik: {},
        companies=COMPANIES,
        raw_dir=tmp_path / "raw",
        sections_dir=tmp_path / "sections",
        chunks_dir=tmp_path / "chunks",
    )
    result = fetcher.fetch_filing(MMM, "10-K", 2016)
    assert result.status == "empty" and result.chunks == 0 and collection.count() == 0


def test_unknown_company_and_bad_arguments_are_rejected(fetcher: FilingFetcher) -> None:
    with pytest.raises(ValueError, match="companies.csv"):
        fetcher.fetch_filing("0000000001", "10-K", 2015)
    for args in [("10-K", 2015, 2), ("10-Q", 2015, None), ("10-Q", 2015, 4), ("8-K", 2015, None)]:
        with pytest.raises(ValueError):
            target_period(*args)


@pytest.mark.integration
def test_fetch_a_real_filing_from_edgar(tmp_path: Path) -> None:
    """3M's FY2013 10-K is outside the project's download window, so it is not indexed."""
    collection = open_collection("fake-model", tmp_path / "chroma")
    fetcher = FilingFetcher(
        FilingSearch(collection, FakeEmbedder(), top_k=5),
        load_config(BASE_CONFIG).chunking,
        raw_dir=tmp_path / "raw",
        sections_dir=tmp_path / "sections",
        chunks_dir=tmp_path / "chunks",
    )
    result = fetcher.fetch_filing(MMM, "10-K", 2013)
    assert result.status == "fetched" and result.chunks > 100
    hits = fetcher.search.search_filings(MMM, 2013, "Item 8", "total assets")
    assert hits and all(h.period == "FY2013" for h in hits)
