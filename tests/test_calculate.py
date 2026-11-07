"""Calculator tool: growth rate, margin, ratio; anything that isn't arithmetic is rejected."""

import pytest

from finqa.tools.calculate import CalculationError, calculate


def test_growth_rate() -> None:
    calc = calculate("(rev_2020 - rev_2019) / rev_2019 * 100", {"rev_2019": 200, "rev_2020": 250})
    assert calc.result == pytest.approx(25.0)
    assert calc.expression == "(rev_2020 - rev_2019) / rev_2019 * 100"
    assert calc.variables == {"rev_2019": 200, "rev_2020": 250}


def test_margin_in_full_units() -> None:
    calc = calculate(
        "(op_income + d_and_a) / revenue * 100",
        {"op_income": 11_512_000_000, "d_and_a": 2_763_000_000, "revenue": 86_392_000_000},
    )
    assert calc.result == pytest.approx(16.5236, rel=1e-4)


def test_ratio_and_average() -> None:
    assert calculate("a / b", {"a": 3, "b": 4}).result == 0.75
    roa = calculate(
        "ni / ((assets_2016 + assets_2017) / 2)",
        {
            "ni": 1_248,
            "assets_2016": 87_270,
            "assets_2017": 87_896,
        },
    )
    assert roa.result == pytest.approx(1_248 / 87_583)


def test_cagr_with_power_and_constants_only() -> None:
    assert calculate("(b / a) ** (1 / 2) - 1", {"a": 100, "b": 121}).result == pytest.approx(0.1)
    assert calculate("-(2 + 3) * 4").result == -20.0


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('x')",
        "a.real",
        "[a][0]",
        "a if a > 0 else b",
        "a > b",
        "lambda: 1",
        "x = 1",
        "a; b",
        "'text'",
        "True + 1",
        "abs(a)",
        "c + 1",  # unknown variable
        "",
        "1 +",
    ],
)
def test_rejects_anything_that_is_not_arithmetic(expression: str) -> None:
    with pytest.raises(CalculationError):
        calculate(expression, {"a": 1.0, "b": 2.0})


def test_rejects_bad_variables_and_bad_results() -> None:
    with pytest.raises(CalculationError, match="division by zero"):
        calculate("a / b", {"a": 1, "b": 0})
    with pytest.raises(CalculationError, match="not finite"):
        calculate("a ** 10000", {"a": 1e10})
    with pytest.raises(CalculationError, match="not a number"):
        calculate("a + 1", {"a": "5"})  # type: ignore[dict-item]
    with pytest.raises(CalculationError, match="invalid variable name"):
        calculate("1", {"not valid": 1})
    with pytest.raises(CalculationError, match="longer than"):
        calculate("+".join(["1"] * 300))
