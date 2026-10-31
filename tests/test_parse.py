"""Section parsing on small synthetic filings that recreate the real cases. No network."""

from finqa.ingestion.parse import (
    heading_span,
    headings,
    locate,
    normalize,
    parse_filing,
    unescape,
    whole_lines,
)

BODY_7 = (
    "Management's discussion and analysis of financial condition. Revenue grew in every "
    "segment during the year, driven by higher volumes and pricing across our businesses. "
    "Operating margin improved as costs fell. See Item 8 of this Annual Report on Form 10-K."
)
BODY_8 = (
    "The consolidated financial statements and the notes to them follow. Our auditors have "
    "issued an unqualified opinion on these statements for every year presented here."
)

ESCAPED_7 = BODY_7.replace(".", "\\.")  # as edgartools writes it: "condition\."

TEN_K = f"""# Annual report

| Item 7. | Management's Discussion and Analysis | 15 |
| Item 8. | Financial Statements | 30 |

**Item 7\\. ** **Management's Discussion and Analysis**

{ESCAPED_7}

| Years ended December 31 (Millions) | 2018 | 2017 |
| --- | --- | --- |
| Net sales \\| total | $ 1,577 | $ 1,373 |

# Item 8. Financial Statements and Supplementary Data

{BODY_8}

# Item 9. Changes in and Disagreements with Accountants

None.
"""


def test_unescape_keeps_table_pipes() -> None:
    assert unescape(r"capital\. year\-on\-year \(net\)") == "capital. year-on-year (net)"
    assert unescape(r"| a \| b |") == r"| a \| b |"


def test_normalize_keeps_letters_and_digits_with_positions() -> None:
    norm, index = normalize("A-1 b.")
    assert norm == "a1b" and index == [0, 2, 4]


# edgartools' plain-text version of Item 7: title, prose, and the table flattened to text.
EDGAR_7 = (
    "Item 7. Management's Discussion and Analysis " + BODY_7 + " Years ended December 31 "
    "(Millions) 2018 2017 Net sales | total 1,577 1,373"
)


def test_locate_skips_table_of_contents_and_keeps_tables() -> None:
    md_norm, md_index = normalize(TEN_K)
    span = locate(EDGAR_7, md_norm, md_index)
    assert span is not None
    start, end = whole_lines(TEN_K, *span)
    text = TEN_K[start:end]
    assert text.startswith("**Item 7") and "| 15 |" not in text  # not the table of contents
    assert text.endswith("| Net sales \\| total | $ 1,577 | $ 1,373 |")  # whole last line


def test_locate_ends_at_the_right_copy_of_repeated_boilerplate() -> None:
    boiler = "This report contains forward looking statements subject to risks and uncertainty. "
    section = "Quarterly results discussion. " * 20 + boiler
    md = "Intro. " + section + ("Other material in the filing. " * 40) + boiler
    md_norm, md_index = normalize(md)
    span = locate(section, md_norm, md_index)
    assert span is not None
    # ends at the first copy of the boilerplate, not the one at the end of the filing
    assert md[span[0] : span[1]] == section.strip()[:-1]  # up to its last letter
    assert "Other material" not in md[span[0] : span[1]]


def test_headings_skip_tables_but_accept_one_cell_heading_tables() -> None:
    md = (
        "| Item 7. | MD&A | 15 |\n"  # table of contents row: skipped
        "| Item 7. Management's Discussion and Analysis |\n| --- |\n\nText.\n"  # Verizon style
        "See Item 8 for details.\n"  # cross-reference mid-line: skipped
        "# Item 8. Financial Statements\n"
    )
    assert [k for _, k in headings(md, "10-K")] == ["Item 7", "Item 8"]


def test_ten_q_headings_assign_parts() -> None:
    md = (
        "PART I\nItem 1. Financial Statements\nx\nItem 2. MD&A\ny\n"
        "PART II\nItem 1. Legal Proceedings\nz\nItem 1A. Risk Factors\nw\n"
    )
    keys = [k for _, k in headings(md, "10-Q")]
    assert keys == ["Part I, Item 1", "Part I, Item 2", "Part II, Item 1", "Part II, Item 1A"]


def test_heading_span_runs_to_the_next_heading() -> None:
    span = heading_span(TEN_K, "10-K", "Item 8")
    assert span is not None
    text = TEN_K[span[0] : span[1]]
    assert text.startswith("# Item 8.") and "Item 9" not in text


def test_parse_filing_methods_and_absent_sections() -> None:
    sections = {s.section: s for s in parse_filing(TEN_K, {"Item 7": EDGAR_7}, "10-K")}
    assert sections["Item 7"].method == "edgartools"
    assert "Net sales" in sections["Item 7"].text and "capital" not in sections["Item 7"].text
    assert sections["Item 7"].text.count("|") >= 9  # the table survived as Markdown
    assert "\\." not in sections["Item 7"].text  # escapes removed
    assert sections["Item 8"].method == "heading"  # no edgartools section: heading fallback
    assert "Item 1" not in sections  # in neither source: absent, not invented


def test_fit_to_headings_moves_split_headings_to_the_right_section() -> None:
    from finqa.ingestion.parse import fit_to_headings

    md = (
        "**Item 7. **\n\n**Management's Discussion**\n\nRevenue grew.\n\n"
        "**Item 7A. ** **Quantitative Disclosures**\n\nRates rose.\n"
    )
    # edgartools-style span: starts after "Item 7." and ends inside the Item 7A heading
    start = md.index("**Management")
    end = md.index("Quantitative") + len("Quantitative")
    s, e = fit_to_headings(md, *whole_lines(md, start, end), "Item 7")
    assert md[s:e] == "**Item 7. **\n\n**Management's Discussion**\n\nRevenue grew."


def test_headings_accept_escaped_dots() -> None:
    md = "**Item 7\. ** **MD&A**\n\nText.\n\n**Item 7A\. ** **Market Risk**\n"
    assert [k for _, k in headings(md, "10-K")] == ["Item 7", "Item 7A"]
