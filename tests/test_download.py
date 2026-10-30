"""Filing download logic: windows, fiscal labels, FinanceBench document matching. No network."""

import datetime as dt

import pytest

from finqa.ingestion.download import (
    FiscalLabel,
    ManifestRow,
    missing_documents,
    parse_doc_name,
    sequence_labels,
    xbrl_labels,
    year_window,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("3M_2018_10K", ("10-K", 2018, "FY")),
        ("3M_2023Q2_10Q", ("10-Q", 2023, "Q2")),
        ("AMERICANWATERWORKS_2021_10K", ("10-K", 2021, "FY")),
    ],
)
def test_parse_doc_name(name: str, expected: tuple) -> None:
    assert parse_doc_name(name) == expected


def test_parse_doc_name_rejects_other_documents() -> None:
    with pytest.raises(ValueError):
        parse_doc_name("PEPSICO_2023_8K_dated-2023-05-05")


def test_year_window_two_before_one_after() -> None:
    assert year_window(["3M_2018_10K", "3M_2022_10K", "3M_2023Q2_10Q"]) == (2016, 2024)


def test_period_format_matches_schema() -> None:
    assert FiscalLabel(2022, "FY", "xbrl").period == "FY2022"
    assert FiscalLabel(2023, "Q3", "xbrl").period == "Q3 FY2023"


FACTS = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {"accn": "A-10K", "fy": 2018, "fp": "FY", "form": "10-K"},
                        {"accn": "A-10Q", "fy": 2019, "fp": "Q1", "form": "10-Q"},
                        {"accn": "A-8K", "fy": 2019, "fp": "Q1", "form": "8-K"},
                    ]
                }
            }
        },
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"accn": "A-10K", "fy": 2018, "fp": "FY", "form": "10-K"},
                        {"accn": "A-10K", "fy": 2018, "fp": "FY", "form": "10-K"},
                        {"accn": "A-10K", "fy": 2017, "fp": "FY", "form": "10-K"},
                    ]
                }
            }
        },
    }
}


def test_xbrl_labels_majority_per_filing() -> None:
    labels = xbrl_labels(FACTS)
    assert labels == {"A-10K": (2018, "FY"), "A-10Q": (2019, "Q1")}  # 8-Ks ignored


def d(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def labels_of(filings, xbrl) -> dict[str, tuple[int, str, str]]:
    return {
        a: (lab.fiscal_year, lab.fiscal_period, lab.source)
        for a, lab in sequence_labels(filings, xbrl).items()
    }


CALENDAR_YEAR = [
    ("q1", "10-Q", d("2022-03-31")),
    ("q2", "10-Q", d("2022-06-30")),
    ("q3", "10-Q", d("2022-09-30")),
    ("k", "10-K", d("2022-12-31")),
    ("next-q1", "10-Q", d("2023-03-31")),
]


def test_calendar_year_company_agreeing_with_xbrl() -> None:
    xbrl = {
        "q1": (2022, "Q1"),
        "q2": (2022, "Q2"),
        "q3": (2022, "Q3"),
        "k": (2022, "FY"),
        "next-q1": (2023, "Q1"),
    }
    assert labels_of(CALENDAR_YEAR, xbrl) == {
        "q1": (2022, "Q1", "xbrl"),
        "q2": (2022, "Q2", "xbrl"),
        "q3": (2022, "Q3", "xbrl"),
        "k": (2022, "FY", "xbrl"),
        "next-q1": (2023, "Q1", "xbrl"),  # after the last 10-K: next fiscal year
    }


def test_stale_xbrl_labels_are_corrected() -> None:
    # AES-style: several 10-Qs all carrying a stale "Q2 FY2022" label
    xbrl = {
        "q1": (2022, "Q1"),
        "q2": (2022, "Q2"),
        "q3": (2022, "Q2"),
        "k": (2022, "FY"),
        "next-q1": (2022, "Q2"),
    }
    labels = labels_of(CALENDAR_YEAR, xbrl)
    assert labels["q3"] == (2022, "Q3", "corrected")
    assert labels["next-q1"] == (2023, "Q1", "corrected")


def test_company_naming_fiscal_year_after_start_year() -> None:
    # Ulta-style: the year ending 2022-01-29 is "fiscal 2021"; the 10-K majority sets this
    filings = [
        ("k21", "10-K", d("2022-01-29")),
        ("q1", "10-Q", d("2022-04-30")),
        ("k22", "10-K", d("2023-01-28")),
        ("k23", "10-K", d("2024-02-03")),  # 53-week year ending in February
    ]
    xbrl = {"k21": (2021, "FY"), "k22": (2022, "FY"), "k23": (2023, "FY")}
    labels = labels_of(filings, xbrl)
    assert labels["k21"][:2] == (2021, "FY") and labels["k23"][:2] == (2023, "FY")
    assert labels["q1"][:2] == (2022, "Q1")


def test_june_fiscal_year_comes_from_the_filings_not_a_fixed_date() -> None:
    # Amcor-style: June year end (the SEC's current year end later changed to December)
    filings = [
        ("q1", "10-Q", d("2019-09-30")),
        ("q2", "10-Q", d("2019-12-31")),
        ("q3", "10-Q", d("2020-03-31")),
        ("k", "10-K", d("2020-06-30")),
    ]
    labels = labels_of(filings, {"k": (2020, "FY")})
    assert [labels[a][:2] for a in ("q1", "q2", "q3", "k")] == [
        (2020, "Q1"),
        (2020, "Q2"),
        (2020, "Q3"),
        (2020, "FY"),
    ]
    assert labels["q1"][2] == "sequence"  # no XBRL label of its own


def test_52_53_week_year_ending_in_early_january() -> None:
    filings = [("k20", "10-K", d("2021-01-02")), ("k21", "10-K", d("2022-01-01"))]
    labels = labels_of(filings, {"k20": (2020, "FY"), "k21": (2021, "FY")})
    assert labels["k20"][:2] == (2020, "FY") and labels["k21"][:2] == (2021, "FY")


def test_period_format_from_label() -> None:
    labels = sequence_labels(CALENDAR_YEAR, {})
    assert labels["k"].period == "FY2022" and labels["q3"].period == "Q3 FY2022"


def row(company: str, form: str, year: int, period: str) -> ManifestRow:
    return ManifestRow(
        company, "0", "acc", form, year, period, "", "", "", "xbrl", "", "", "", 0, ""
    )


def test_missing_documents() -> None:
    manifest = [row("3M", "10-K", 2018, "FY"), row("3M", "10-Q", 2023, "Q2")]
    docs = {"3M": {"3M_2018_10K", "3M_2023Q2_10Q", "3M_2022_10K"}}
    assert missing_documents(docs, manifest) == ["3M: 3M_2022_10K"]


def test_save_retries_when_windows_briefly_locks_the_file(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from finqa.ingestion import files

    real_replace = Path.replace
    failures = {"left": 2}

    def flaky_replace(self, target):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("[WinError 5] Access is denied")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    sleeps: list[float] = []
    target = tmp_path / "a.md"
    files.save_atomic(target, "text", sleep=sleeps.append)
    assert target.read_text(encoding="utf-8") == "text"
    assert len(sleeps) == 2 and not (tmp_path / "a.md.tmp").exists()


def test_save_gives_up_after_all_attempts(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from finqa.ingestion import files

    def always_locked(self, target):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(Path, "replace", always_locked)
    with pytest.raises(PermissionError):
        files.save_atomic(tmp_path / "a.md", "text", attempts=3, sleep=lambda s: None)
