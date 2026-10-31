"""Chunking and unit scale on small synthetic sections modelled on real filings. No network."""

from finqa.config import ChunkingConfig
from finqa.ingestion.chunk import (
    Table,
    blocks,
    chunk_filing,
    count_tokens,
    detect_scale,
    section_slug,
    table_chunks,
    table_scale,
    text_chunks,
)

CFG = ChunkingConfig(text_max_tokens=60, overlap_tokens=15, table_max_tokens=80)
META = {
    "cik": "0000066740",
    "ticker": "MMM",
    "form": "10-K",
    "fiscal_year": "2018",
    "period": "FY2018",
    "accession": "0000066740-19-000010",
}

SECTION = """Revenue grew in every segment. Pricing helped.

The following table shows net sales by segment.
(in millions)

| (Millions) | 2018 | 2017 |
| --- | --- | --- |
| Industrial | $ 12,267 | $ 11,866 |
| Safety | 6,827 | 6,235 |

| Item 7A. Quantitative and Qualitative Disclosures About Market Risk |
| --- |

Rates rose during the year."""


def test_blocks_separate_tables_with_captions() -> None:
    parts = blocks(SECTION)
    tables = [b for b in parts if isinstance(b, Table)]
    assert len(tables) == 1
    assert tables[0].caption == ["The following table shows net sales by segment.", "(in millions)"]
    assert tables[0].rows[0] == "| (Millions) | 2018 | 2017 |"
    # the single-column "table" is a heading, kept as text
    assert "Item 7A. Quantitative and Qualitative Disclosures About Market Risk" in parts


def test_long_paragraph_above_a_table_gives_its_last_sentence_as_caption() -> None:
    prose = "Membership grew. " * 30 + "Our membership was made up of the following (in thousands):"
    parts = blocks(prose + "\n\n|  | 2022 |\n| --- | --- |\n| Gold Star | 54,000 |")
    t = next(b for b in parts if isinstance(b, Table))
    assert t.caption == ["Our membership was made up of the following (in thousands):"]
    assert table_scale(t.caption, t.rows) == 1e3


def test_unit_scale_detected_on_sample_tables() -> None:
    assert detect_scale("(in millions, except per share data)") == 1e6
    assert detect_scale("(Dollars in thousands)") == 1e3
    assert detect_scale("($ in billions)") == 1e9
    assert detect_scale("(millions of dollars)") == 1e6
    assert detect_scale("Millions") == 1e6
    assert detect_scale("Net sales increased 5% to $3.2 billion") is None  # prose, not a scale
    # header row wins over the caption
    rows = ["| (In thousands) | 2023 |", "| --- | --- |", "| Revenue | 5,120 |"]
    assert table_scale(["Amounts in millions"], rows) == 1e3
    # caption when the header says nothing
    rows = ["|  | 2023 |", "| --- | --- |", "| Revenue | 5,120 |"]
    assert table_scale(["(in millions, except per share amounts)"], rows) == 1e6
    # nothing stated: left empty, never guessed
    assert table_scale(["Maturities of lease liabilities were as follows:"], rows) is None


def test_split_table_repeats_its_header() -> None:
    header = ["| (Millions) | 2018 | 2017 |", "| --- | --- | --- |"]
    body = [f"| Segment {i} | {i},100 | {i},050 |" for i in range(30)]
    table = Table(["Net sales by segment"], header + body)
    pieces = table_chunks(table, 80)
    assert len(pieces) > 1
    for piece in pieces:
        assert piece.startswith("Net sales by segment\n\n" + "\n".join(header))
        assert count_tokens(piece) <= 80
    # every row appears exactly once across the pieces
    rows = [r for p in pieces for r in p.split("\n") if r.startswith("| Segment")]
    assert rows == body


def test_oversized_rows_and_headers_still_fit() -> None:
    paragraph = "| " + "Investment securities were investment grade. " * 40 + "|"
    table = Table([], [paragraph, "| --- |", "| Debt | 1,200 |", "| Equity | 300 |"])
    pieces = table_chunks(table, 80)
    assert len(pieces) > 1 and all(count_tokens(p) <= 80 for p in pieces)
    assert "| Equity | 300 |" in pieces[-1]


def test_small_table_is_one_chunk() -> None:
    table = Table([], ["| a | b |", "| --- | --- |", "| 1 | 2 |"])
    assert table_chunks(table, 80) == ["| a | b |\n| --- | --- |\n| 1 | 2 |"]


def test_text_chunks_respect_size_paragraphs_and_overlap() -> None:
    paragraphs = [f"Paragraph {k} sentence one is here. Sentence two ends it." for k in range(8)]
    chunks = text_chunks(paragraphs, CFG)
    assert len(chunks) > 1
    assert all(count_tokens(c) <= CFG.text_max_tokens for c in chunks)
    # cut on paragraph boundaries; each later chunk opens with the previous chunk's close
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.split("\n\n")[0].strip() in prev
    # every paragraph survives
    assert all(any(p in c for c in chunks) for p in paragraphs)


def test_overlong_paragraph_is_cut_on_sentences() -> None:
    para = " ".join(f"Sentence number {i} about revenue." for i in range(40))
    chunks = text_chunks([para], CFG)
    assert len(chunks) > 1
    assert all(count_tokens(c) <= CFG.text_max_tokens for c in chunks)
    assert all(c.rstrip().endswith(".") for c in chunks)


def test_chunk_ids_are_stable_and_metadata_is_filled() -> None:
    sections = [{"section": "Item 7", "text": SECTION}, {"section": "Item 8", "text": "Notes."}]
    first = chunk_filing(sections, META, CFG)
    second = chunk_filing(sections, META, CFG)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
    ids = [c.chunk_id for c in first]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "0000066740-0000066740-19-000010-item-7-0"
    table = next(c for c in first if c.is_table)
    assert table.unit_scale == 1e6 and table.period == "FY2018" and table.fiscal_year == 2018
    assert all(c.unit_scale is None for c in first if not c.is_table)


def test_section_slug() -> None:
    assert section_slug("Part I, Item 2") == "part-i-item-2"
    assert section_slug("Item 1A") == "item-1a"
