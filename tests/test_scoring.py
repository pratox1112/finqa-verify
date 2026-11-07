"""Scoring (ROADMAP P2.3): gold-only correctness, tolerance, refusals, failures, the judge."""

import pytest

from finqa.eval import scoring
from finqa.eval.scoring import Gold, Judgment, score, selective_accuracy, within_tolerance
from finqa.schemas import Claim

NUMBER_GOLD = Gold("q1", "$1577.00", "number", 1_577_000_000.0, "USD")
TEXT_GOLD = Gold("q2", "No, working capital was -$1561M.", "text_with_numbers", None, "")


def claim(value: float, unit: str = "USD", cid: str = "c1") -> Claim:
    return Claim(
        claim_id=cid, metric="capex", value=value, unit=unit, period="FY2018", chunk_ids=[]
    )


def numeric(value: float, tolerance: float = 0.01) -> str:
    s = score("q1", "capex?", NUMBER_GOLD, [claim(value)], "c1", "", None, tolerance)
    return s.outcome


@pytest.mark.parametrize(
    ("value", "outcome"),
    [
        (1_577_000_000.0, "correct"),  # exact
        (1_590_000_000.0, "correct"),  # inside 1%
        (1_592_770_000.0, "correct"),  # at the 1% edge
        (1_600_000_000.0, "incorrect"),  # outside
        (1_577_000.0, "incorrect"),  # wrong scale (thousands for millions)
    ],
)
def test_numeric_tolerance(value: float, outcome: str):
    assert numeric(value) == outcome


def test_zero_gold_needs_exact_zero():
    assert within_tolerance(0.0, 0.0, 0.01)
    assert not within_tolerance(0.001, 0.0, 0.01)


def test_numeric_uses_the_answer_claim_only():
    claims = [claim(1_577_000_000.0, cid="c1"), claim(5.0, cid="c2")]
    s = score("q1", "capex?", NUMBER_GOLD, claims, "c2", "", None, 0.01)
    assert s.outcome == "incorrect"
    s = score("q1", "capex?", NUMBER_GOLD, [claim(1.0)], None, "1", None, 0.01)
    assert (s.outcome, s.reason) == ("incorrect", "no answer claim")


def test_failed_generation_is_incorrect():
    s = score("q1", "?", NUMBER_GOLD, [], None, "", "api_error: 429", 0.01)
    assert (s.outcome, s.method) == ("incorrect", "failed")


@pytest.mark.parametrize(
    "text",
    [
        "The capital expenditure cannot be determined from the information provided.",
        "This figure is not available in the filing.",
        "I don't know.",
        "Insufficient information to answer.",
        "The excerpts do not contain Netflix's FY2015 capital expenditures.",
        "The provided excerpts don't include the cash flow statement.",
        "The filing does not provide enough detail to compute the ratio.",
        "This figure is not included in the provided excerpts.",
    ],
)
def test_refusals(text: str):
    assert score("q1", "?", NUMBER_GOLD, [], None, text, None, 0.01).outcome == "refused"


@pytest.mark.parametrize(
    "text",
    [
        "Revenue does not include excise taxes; it was $2B.",
        "The company did not disclose a dividend cut and kept paying.",
    ],
)
def test_refusal_wording_with_claims_is_an_answer(text: str):
    s = score("q1", "?", NUMBER_GOLD, [claim(1_577_000_000.0)], "c1", text, None, 0.01)
    assert s.outcome == "correct"


def test_wrong_number_is_not_a_refusal():
    s = score("q1", "?", NUMBER_GOLD, [claim(2e9)], "c1", "Capex was $2B.", None, 0.01)
    assert s.outcome == "incorrect"


def test_text_gold_goes_to_the_judge():
    seen = []

    def judge(question, gold_answer, model_answer):
        seen.append((question, gold_answer, model_answer))
        return Judgment(correct=True, reason="same conclusion and figure")

    s = score("q2", "Positive WC?", TEXT_GOLD, [], None, "No, it was -$1.56B.", None, 0.01, judge)
    assert (s.outcome, s.method) == ("correct", "judge")
    assert seen == [("Positive WC?", TEXT_GOLD.answer, "No, it was -$1.56B.")]


def test_text_gold_without_judge_is_an_error():
    with pytest.raises(ValueError, match="judge"):
        score("q2", "?", TEXT_GOLD, [], None, "No.", None, 0.01)


def test_selective_accuracy_ignores_refusals():
    scores = [
        scoring.AnswerScore("a", "correct", "numeric"),
        scoring.AnswerScore("b", "incorrect", "numeric"),
        scoring.AnswerScore("c", "refused", "refusal"),
    ]
    assert selective_accuracy(scores) == (1, 2)


def test_gold_loads_from_the_audit():
    gold = scoring.load_gold()
    assert len(gold) == 150
    numbers = [g for g in gold.values() if g.answer_kind == "number"]
    assert all(g.value is not None for g in numbers)


def test_judge_prompt_exists():
    assert "Judgment" in scoring.JUDGE_PROMPT_PATH.read_text()


ROA = (
    "What is the FY2017 return on assets (ROA) for Coca Cola? "
    "Round your answer to two decimal places."
)
RATIO_GOLD = Gold("q3", "0.01", "number", 0.01, "ratio")


def test_percent_answer_for_a_ratio_gold_is_converted_and_rounded():
    # Coca-Cola FY2017 ROA (financebench_id_03473): 1.35% = 0.0135, which rounds to 0.01
    s = score("q3", ROA, RATIO_GOLD, [claim(1.35, "%")], "c1", "ROA was 1.35%.", None, 0.01)
    assert s.outcome == "correct" and "as ratio: 0.0135" in s.reason


def test_ratio_answer_for_a_ratio_gold_is_rounded():
    s = score("q3", ROA, RATIO_GOLD, [claim(0.0135, "ratio")], "c1", "0.0135", None, 0.01)
    assert s.outcome == "correct"


def test_rounding_still_rejects_a_different_value():
    s = score("q3", ROA, RATIO_GOLD, [claim(1.6, "%")], "c1", "ROA was 1.6%.", None, 0.01)
    assert s.outcome == "incorrect"  # 0.016 rounds to 0.02


def test_without_a_rounding_instruction_the_tolerance_decides():
    s = score("q3", "What is the ROA?", RATIO_GOLD, [claim(1.35, "%")], "c1", "", None, 0.01)
    assert s.outcome == "incorrect"


def test_ratio_answer_for_a_percent_gold_is_converted():
    gold = Gold("q4", "55.1%", "number", 55.1, "%")
    q = "What is the gross margin? Round your answer to one decimal place."
    assert score("q4", q, gold, [claim(0.551, "ratio")], "c1", "", None, 0.01).outcome == "correct"
    assert score("q4", q, gold, [claim(0.5514, "ratio")], "c1", "", None, 0.01).outcome == (
        "correct"
    )


def test_negative_ratio_rounds():
    # AES FY2022 ROA (financebench_id_10420): gold -0.02
    gold = Gold("q5", "-0.02", "number", -0.02, "ratio")
    q = "What is AES's FY2022 ROA? Round your answer to two decimal places."
    assert score("q5", q, gold, [claim(-1.7, "%")], "c1", "", None, 0.01).outcome == "correct"
    assert score("q5", q, gold, [claim(-0.4, "%")], "c1", "", None, 0.01).outcome == "incorrect"


@pytest.mark.parametrize(
    ("question", "n"),
    [
        ("Round your answer to two decimal places.", 2),
        ("Please round to one decimal place.", 1),
        ("Answer rounded to 3 decimal places", 3),
        ("What is the capex in USD millions?", None),
    ],
)
def test_rounding_decimals(question: str, n: int | None):
    assert scoring.rounding_decimals(question) == n
