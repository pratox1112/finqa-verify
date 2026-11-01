"""Automated quality checks, on synthetic chunks and sections. No network."""

from collections import Counter

from finqa.ingestion.qa_check import (
    ELSEWHERE,
    MISSING,
    NO_LABEL,
    NO_XBRL,
    PASS,
    SCALE,
    Result,
    check_metric,
    check_sections,
    garbled,
    numbers,
    render,
    verdict,
)
from finqa.schemas import Chunk


def chunk(i: int, text: str, scale: float | None, section: str = "Item 8") -> Chunk:
    return Chunk(
        chunk_id=f"0000040704-0001193125-20-186469-item-8-{i}",
        cik="0000040704",
        ticker="GIS",
        form="10-K",
        fiscal_year=2020,
        period="FY2020",
        section=section,
        is_table=True,
        unit_scale=scale,
        text=text,
        source_accession="0001193125-20-186469",
    )


SHEET = (
    "| (In Millions) | 2020 | 2019 |\n| --- | --- | --- |\n"
    "| Total assets | $ | 30,806.7 | 30,111.2 |"
)
ASSETS = [30_806_700_000.0]


def test_numbers_reads_values_with_their_decimals_and_skips_the_label() -> None:
    assert numbers("| Net cash (used in) 2020 | $ | (1,046) | 17,626.6 | 12% | n/a |") == [
        (1046.0, 0),
        (17626.6, 1),
        (12.0, 0),
    ]


def test_value_at_the_detected_scale_in_item_8_passes() -> None:
    assert check_metric("total_assets", [chunk(1, SHEET, 1e6)], ASSETS).status == PASS


def test_value_only_at_another_scale_is_a_scale_problem() -> None:
    result = check_metric("total_assets", [chunk(1, SHEET, None)], ASSETS)
    assert result.status == SCALE and "item-8-1" in result.detail
    # a short number fitting by accident ("4" billions ~ revenue) is not evidence
    tiny = "|  | 2020 |\n| --- | --- |\n| Note | 31 |"
    assert check_metric("total_assets", [chunk(1, tiny, None)], [31_200_000_000.0]).status == (
        MISSING
    )


def test_where_the_value_turns_up_decides_the_status() -> None:
    unlabeled = SHEET.replace("Total assets", "")
    assert check_metric("total_assets", [chunk(1, unlabeled, 1e6)], ASSETS).status == NO_LABEL
    md_and_a = chunk(1, SHEET, 1e6, section="Item 7")
    assert check_metric("total_assets", [md_and_a], ASSETS).status == ELSEWHERE
    assert check_metric("total_assets", [chunk(1, SHEET, 1e6)], [1.0e12]).status == MISSING
    assert check_metric("total_assets", [chunk(1, SHEET, 1e6)], []).status == NO_XBRL
    # a labelled match in Item 8 wins over an earlier match elsewhere
    both = [md_and_a, chunk(2, SHEET, 1e6)]
    assert check_metric("total_assets", both, ASSETS).status == PASS


def test_sections_must_open_with_their_title_and_text_must_not_be_garbled() -> None:
    sections = [
        {"section": "Item 7", "text": "# Item 7. Management's Discussion and Analysis"},
        {"section": "Item 1A", "text": "We webcast our earnings calls on our website."},
    ]
    assert check_sections(sections) == [
        'Item 1A starts "We webcast our earnings calls on our website.…"'
    ]
    assert garbled([chunk(1, "the Company\x92s results \x97 and �", 1e6)]) == 3
    assert garbled([chunk(1, "the Company’s results — fine", 1e6)]) == 0


def test_verdicts_and_report() -> None:
    row = {"company": "General Mills", "period": "FY2020", "fiscal_year": "2020"}

    def result(status: str, untitled: list[str] | None = None, bad: int = 0) -> dict:
        return {
            "row": row,
            "tables": [Result("total_assets", status)],
            "untitled": untitled or [],
            "garbled": bad,
        }

    assert verdict(result(PASS)) == "pass"
    assert verdict(result(NO_LABEL)) == "warn"
    assert verdict(result(PASS, untitled=["Item 1 starts ..."])) == "warn"
    assert verdict(result(SCALE)) == "flag"
    assert verdict(result(PASS, bad=2)) == "flag"
    report = render([result(PASS), result(SCALE)], Counter({("General Mills", 2020): 3}))
    assert "**2 10-Ks:** 1 pass, 0 warn, 1 flag." in report
    assert "| General Mills | FY2020 | 3 | flag | total_assets: scale () |" in report
