"""Shared number reader (ROADMAP P1.2)."""

import pytest

from finqa.verifiers.numbers import extract_numbers, gold_value, parse_number, question_unit


# The six formats named in the roadmap's acceptance criteria.
@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("$1.2B", 1.2e9, "USD"),
        ("1.2 billion", 1.2e9, None),
        ("$1.2 billion", 1.2e9, "USD"),
        ("1,200 million", 1.2e9, None),
        ("(1,234)", -1234.0, None),
        ("12.5%", 12.5, "%"),
        ("$3.45 per share", 3.45, "USD/share"),
    ],
)
def test_roadmap_formats(text: str, value: float, unit: str | None) -> None:
    parsed = parse_number(text)
    assert parsed is not None
    assert parsed.value == pytest.approx(value)
    assert parsed.unit == unit


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("$1,577.00", 1577.0, "USD"),
        ("-$156 million", -156e6, "USD"),
        ("$450M", 450e6, "USD"),
        ("($12.3 million)", -12.3e6, "USD"),
        ("-3.7", -3.7, None),
        ("−0.02", -0.02, None),  # Unicode minus
        ("1.4x", 1.4, "ratio"),
        ("42.69 days", 42.69, "days"),
        ("2.5 million shares", 2.5e6, "shares"),
        ("0.5 percentage points", 0.5, "%"),
        ("$0.40 per diluted share", 0.40, "USD/share"),
        ("0", 0.0, None),
    ],
)
def test_more_formats(text: str, value: float, unit: str | None) -> None:
    parsed = parse_number(text)
    assert parsed is not None
    assert parsed.value == pytest.approx(value)
    assert parsed.unit == unit


@pytest.mark.parametrize("text", ["Yes", "Data Center", "Revenue grew 5% to $2B", ""])
def test_parse_number_needs_exactly_one_number(text: str) -> None:
    assert parse_number(text) is None


def test_extract_numbers_from_sentence() -> None:
    found = extract_numbers(
        "Yes. Corning had positive working capital of $831 million by FY 2022 close; "
        "margins fell from 36.8% to 34.6% and the quick ratio was 1.4x."
    )
    assert [(n.value, n.unit) for n in found] == [
        (831e6, "USD"),
        (36.8, "%"),
        (34.6, "%"),
        (1.4, "ratio"),
    ]


def test_bare_years_are_not_numbers() -> None:
    assert extract_numbers("in FY 2022 and fiscal 2021") == []
    assert [n.value for n in extract_numbers("$2022 million")] == [2022e6]  # has a unit


@pytest.mark.parametrize(
    ("question", "unit", "scale"),
    [
        ("What is the FY2018 capital expenditure amount (in USD millions) for 3M?", "USD", 1e6),
        ("What is the FY2018 net PPNE for 3M? Answer in USD billions.", "USD", 1e9),
        ("in the future in USD million?", "USD", 1e6),
        ("revenue growth (in units of percents and round to one decimal place)", "%", 1.0),
        ("What is the FY2022 unadjusted EBITDA % margin for PepsiCo?", "%", 1.0),
        ("What is the FY2019 fixed asset turnover ratio?", "ratio", 1.0),
        ("What is the FY2017 return on assets (ROA) for Coca Cola?", "ratio", 1.0),
        ("What is FY2018 days payable outstanding (DPO) for Walmart?", "days", 1.0),
        ("What is the FY2019 cash conversion cycle (CCC) for General Mills?", "days", 1.0),
        ("What was diluted EPS?", "USD/share", 1.0),
        ("What restructuring costs are outlined? If none, state 0.", None, 1.0),
    ],
)
def test_question_unit(question: str, unit: str | None, scale: float) -> None:
    hint = question_unit(question)
    assert (hint.unit, hint.scale) == (unit, scale)


@pytest.mark.parametrize(
    ("question", "answer", "value", "unit"),
    [
        # Decision: the question's stated unit applies to a bare gold number.
        ("Capital expenditure (in USD millions) for 3M?", "$1577.00", 1.577e9, "USD"),
        ("Net PPNE for 3M? Answer in USD billions.", "$8.70", 8.7e9, "USD"),
        ("Revenue growth in units of percents?", "30.8%", 30.8, "%"),
        ("Revenue growth in units of percents?", "-3.7", -3.7, "%"),
        ("Fixed asset turnover ratio?", "24.26", 24.26, "ratio"),
        ("Days payable outstanding (DPO)?", "42.69", 42.69, "days"),
        # An answer that already carries its own scale is not scaled again.
        ("Capex (in USD millions)?", "$1.6 billion", 1.6e9, "USD"),
        ("Dividends per share?", "$0.40", 0.40, "USD/share"),
    ],
)
def test_gold_value(question: str, answer: str, value: float, unit: str) -> None:
    gold = gold_value(question, answer)
    assert gold is not None
    assert gold.value == pytest.approx(value)
    assert gold.unit == unit


def test_gold_value_is_none_for_sentences() -> None:
    assert gold_value("Is working capital positive?", "Yes, it was $831 million.") is None
