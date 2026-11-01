"""XBRL lookup on a small extract of 3M's real company facts (tests/fixtures/xbrl). No network.

The fixture keeps 3M's OperatingIncomeLoss, Assets and effective tax rate facts for periods
ending 2016-12-31 to 2018-12-31, copied unchanged from the SEC companyfacts file.
"""

from pathlib import Path

from finqa.ingestion.xbrl import (
    Fact,
    Metric,
    distinct_values,
    duration_months,
    lookup,
    lookup_metric,
    period_end,
    restatements,
)

ROOT = Path(__file__).parent / "fixtures" / "xbrl"
CIK = "0000066740"  # 3M
MANIFEST = [
    {"cik": CIK, "period": "FY2017", "period_of_report": "2017-12-31"},
    {"cik": CIK, "period": "FY2018", "period_of_report": "2018-12-31"},
    {"cik": CIK, "period": "Q3 FY2018", "period_of_report": "2018-09-30"},
]
METRICS = {
    "operating_income": Metric("operating_income", "USD", "duration", ("OperatingIncomeLoss",)),
    "total_assets": Metric("total_assets", "USD", "instant", ("Assets",)),
    "effective_tax_rate": Metric(
        "effective_tax_rate", "%", "duration", ("EffectiveIncomeTaxRateContinuingOperations",)
    ),
    "inventory": Metric("inventory", "USD", "instant", ("InventoryNet",)),  # not in fixture
}


def test_lookup_returns_every_value_of_a_known_restated_item() -> None:
    # 3M's 2017 operating income: $7,820M in its FY2017 10-K; recast to $7,692M (pension
    # cost reclassification, ASU 2017-07) in a May 2018 8-K and later 10-Ks.
    found = lookup(CIK, "OperatingIncomeLoss", "USD", "2017-12-31", 12, ROOT)
    assert [(f.value, f.form, f.accession) for f in found] == [
        (7_820_000_000, "10-K", "0001558370-18-000535"),
        (7_692_000_000, "8-K", "0001558370-18-004256"),
        (7_692_000_000, "10-K", "0001558370-19-000470"),
        (7_692_000_000, "10-K", "0001558370-20-000581"),
    ]
    assert distinct_values(found) == [7_820_000_000, 7_692_000_000]


def test_periods_are_matched_by_dates_not_fiscal_labels() -> None:
    found = lookup(CIK, "OperatingIncomeLoss", "USD", "2017-12-31", 12, ROOT)
    # the FY2018 10-K's comparative column carries the filing's own label, fy=2018
    assert {f.fiscal_year for f in found} == {2017, 2018, 2019}
    assert lookup(CIK, "OperatingIncomeLoss", "USD", "2017-12-31", 3, ROOT) == []  # no Q4


def test_lookup_metric_by_schema_period() -> None:
    assets = lookup_metric(CIK, "total_assets", "FY2017", METRICS, MANIFEST, ROOT)
    assert {f.value for f in assets} == {37_987_000_000}
    assert all(f.start is None for f in assets)  # balance sheet: instant at period end
    etr = lookup_metric(CIK, "effective_tax_rate", "FY2018", METRICS, MANIFEST, ROOT)
    assert {f.value for f in etr} == {23.4} and etr[0].unit == "%"  # 0.234 in XBRL
    assert lookup_metric(CIK, "inventory", "FY2018", METRICS, MANIFEST, ROOT) == []  # no value


def test_period_end_maps_year_to_date_periods_to_their_quarter() -> None:
    assert period_end(CIK, "FY2018", MANIFEST) == "2018-12-31"
    assert period_end(CIK, "9M FY2018", MANIFEST) == "2018-09-30"
    assert period_end("66740", "Q3 FY2018", MANIFEST) == "2018-09-30"


def test_restatements_flag_periods_reported_with_different_values() -> None:
    found = restatements(CIK, METRICS, since="2016-01-01", root=ROOT)
    periods = {(m, fs[0].start, fs[0].end) for m, fs in found}
    assert ("operating_income", "2017-01-01", "2017-12-31") in periods
    assert ("operating_income", "2016-01-01", "2016-12-31") in periods
    assert not any(m == "total_assets" and fs[0].end == "2017-12-31" for m, fs in found)


def test_duration_months_handles_52_week_years() -> None:
    def fact(start: str | None, end: str) -> Fact:
        return Fact("X", "USD", start, end, 1.0, "a", "10-K", "2020-01-01", None, None)

    assert duration_months(fact("2018-02-04", "2019-02-02")) == 12  # 52 weeks
    assert duration_months(fact("2018-07-01", "2018-09-29")) == 3
    assert duration_months(fact(None, "2018-09-29")) is None
