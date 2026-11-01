"""Review sheets and the QA results table, on synthetic chunks. No network."""

from pathlib import Path

from finqa.ingestion.review import (
    filing_url,
    find_statements,
    read_results,
    render_checks,
    render_sheet,
    review_filings,
    sample_tables,
    scale_name,
)
from finqa.schemas import Chunk


def chunk(i: int, text: str, is_table: bool, scale: float | None, section: str = "Item 8") -> Chunk:
    return Chunk(
        chunk_id=f"0000066740-0000066740-23-000010-item-8-{i}",
        cik="0000066740",
        ticker="MMM",
        form="10-K",
        fiscal_year=2022,
        period="FY2022",
        section=section,
        is_table=is_table,
        unit_scale=scale,
        text=text,
        source_accession="0000066740-23-000010",
    )


def table(title: str, rows: list[str]) -> str:
    return "\n".join([f"### {title}", "| (Millions) | 2022 | 2021 |", "| --- | --- | --- |", *rows])


INCOME = table(
    "Consolidated Statement of Income",
    [f"| Line {i} | 1,{i:03d} | 1,{i:03d} |" for i in range(8)]
    + ["| Net income | 5,777 | 5,921 |", "| Diluted earnings per share | 10.18 | 10.12 |"],
)
BALANCE = table(
    "Consolidated Balance Sheet",
    [f"| Asset {i} | 2,{i:03d} | 2,{i:03d} |" for i in range(8)]
    + ["| Total assets | 46,455 | 47,072 |", "| Total liabilities | 31,685 | 31,955 |"],
)
CASH = table(
    "Consolidated Statement of Cash Flows",
    ["| Cash flows from operating activities | | |"]
    + [f"| Item {i} | 3,{i:03d} | 3,{i:03d} |" for i in range(8)]
    + ["| Net cash used in investing activities | (1,046) | (1,317) |"],
)
CHUNKS = [
    chunk(0, "Revenue grew in every segment.", False, None, "Item 7"),
    chunk(1, INCOME, True, 1e6),
    chunk(2, BALANCE, True, 1e6),
    chunk(3, CASH, True, 1e6),
    chunk(4, "| Lease | 2023 |\n| --- | --- |\n| Payments | 1,234 |", True, None),
    chunk(5, "| Debt | 2023 |\n| --- | --- |\n| Notes | 5,678 |", True, 1e3),
]


def test_statements_are_found_by_their_line_items() -> None:
    found = find_statements(CHUNKS)
    assert {k: c.chunk_id[-1] for k, c in found.items()} == {
        "Income statement": "1",
        "Balance sheet": "2",
        "Cash flow statement": "3",
    }


def test_sampled_tables_include_one_without_a_scale_and_are_reproducible() -> None:
    skip = {c.chunk_id for c in find_statements(CHUNKS).values()}
    first = sample_tables(CHUNKS, skip, "seed")
    assert first == sample_tables(CHUNKS, skip, "seed")
    assert any(c.unit_scale is None for c in first)
    assert not skip & {c.chunk_id for c in first}


def test_sheet_shows_sections_statements_and_scales() -> None:
    row = {
        "accession": "0000066740-23-000010",
        "cik": "0000066740",
        "period": "FY2022",
        "period_of_report": "2022-12-31",
        "filing_date": "2023-02-08",
    }
    sections = [{"section": "Item 7", "method": "edgartools", "text": "# Item 7. MD&A | text"}]
    sheet = render_sheet("3M", row, sections, CHUNKS)
    assert sheet.startswith("# QA sheet: 3M, 10-K FY2022")
    assert filing_url("0000066740", row["accession"]) in sheet
    assert "| Item 7 | edgartools |" in sheet and "MD&A \\| text" in sheet  # pipes escaped
    assert sheet.count("detected unit scale: **millions**") == 3
    assert "\n### Consolidated" not in sheet  # captions are not sheet headings
    assert scale_name(None) == "none" and scale_name(1e3) == "thousands"


def test_results_table_keeps_filled_in_rows(tmp_path: Path) -> None:
    filings = {"3M": {"period": "FY2022"}, "Adobe": {"period": "FY2022"}}
    first = render_checks(filings, {})
    path = tmp_path / "QA_CHECKS.md"
    path.write_text(
        first.replace(
            "| 3M | FY2022 | [sheet](qa_sheets/3m.md) |  |  |  |  |  |  |  |",
            "| 3M | FY2022 | [sheet](qa_sheets/3m.md) | Pratosh | 2026-11-01 | ok | ok | ok | ok |"
            " fine |",
        ),
        encoding="utf-8",
    )
    again = render_checks(filings, read_results(path))
    assert "| Pratosh | 2026-11-01 | ok | ok | ok | ok | fine |" in again
    assert "| Adobe | FY2022 | [sheet](qa_sheets/adobe.md) |  |" in again


def test_review_filing_is_the_most_asked_about_10k(tmp_path: Path) -> None:
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "company,doc_name,in_scope\n"
        "3M,3M_2018_10K,True\n3M,3M_2022_10K,True\n3M,3M_2022_10K,True\n"
        "3M,3M_2023Q2_10Q,True\n3M,3M_2019_10K,False\n",
        encoding="utf-8",
    )
    manifest = [
        {"company": "3M", "form": "10-K", "period": p, "accession": p} for p in ("FY2018", "FY2022")
    ]
    assert review_filings(manifest, audit)["3M"]["period"] == "FY2022"
