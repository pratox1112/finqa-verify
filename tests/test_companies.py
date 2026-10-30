"""Company table: resolution logic with a fake SEC client, and the committed table."""

import re
from typing import Any

import pytest

from finqa.ingestion import companies as co

TICKERS = {
    "MMM": {"cik_str": 66740, "ticker": "MMM", "title": "3M CO"},
    "XYZ": {"cik_str": 1512673, "ticker": "XYZ", "title": "Block, Inc."},
}
SUBMISSIONS = {
    "0000066740": {
        "name": "3M CO",
        "tickers": ["MMM"],
        "fiscalYearEnd": "1231",
        "formerNames": [{"name": "MINNESOTA MINING & MANUFACTURING CO"}],
    },
    "0001512673": {
        "name": "Block, Inc.",
        "tickers": ["XYZ"],
        "fiscalYearEnd": "1231",
        "formerNames": [{"name": "Square, Inc."}],
    },
    "0000718877": {
        "name": "Activision Blizzard, Inc.",
        "tickers": [],
        "fiscalYearEnd": "1231",
        "formerNames": [],
    },
}


class FakeSec:
    def __init__(self, search: dict[str, list[str]] | None = None) -> None:
        self.search = search or {"activision blizzard": ["0000718877"]}

    def tickers(self) -> dict[str, dict[str, Any]]:
        return TICKERS

    def submissions(self, cik: str) -> dict[str, Any]:
        return SUBMISSIONS[cik]

    def search_company(self, name: str) -> list[str]:
        return self.search.get(name, [])


def test_resolves_by_ticker_falling_back_to_older_ticker_and_search() -> None:
    rows = {r["company"]: r for r in co.build(["3M", "Block", "Activision Blizzard"], FakeSec())}
    assert rows["3M"]["cik"] == "0000066740"
    assert rows["3M"]["former_names"] == "MINNESOTA MINING & MANUFACTURING CO"
    assert rows["Block"]["ticker"] == "XYZ" and rows["Block"]["tickers"] == "XYZ;SQ"
    assert rows["Activision Blizzard"]["cik"] == "0000718877"  # delisted: found by name
    assert rows["Activision Blizzard"]["ticker"] == "ATVI"
    assert rows["Block"]["aliases"].startswith("Block;Square")


def test_ambiguous_search_is_an_error() -> None:
    sec = FakeSec(search={"activision blizzard": ["0000000001", "0000000002"]})
    with pytest.raises(co.ResolutionError, match="2 CIKs"):
        co.build(["Activision Blizzard"], sec)


def test_unknown_company_is_an_error() -> None:
    with pytest.raises(co.ResolutionError, match="no seed"):
        co.build(["Not A Company"], FakeSec())


# The committed table (ROADMAP P1.3 acceptance): every in-scope company maps to one CIK.


def test_every_in_scope_company_has_exactly_one_cik() -> None:
    rows = co.load()
    names = [r["company"] for r in rows]
    assert sorted(names) == co.in_scope_companies()
    assert len(set(names)) == len(names)
    ciks = [r["cik"] for r in rows]
    assert all(re.fullmatch(r"\d{10}", c) for c in ciks)
    assert len(set(ciks)) == len(ciks)
