"""Company table (ROADMAP P1.3): data/companies.csv, one row per in-scope company.

Each FinanceBench company name resolves to exactly one SEC CIK: first through its ticker(s)
in the SEC ticker file, else (delisted companies) through the SEC company search. The SEC
submissions file then gives the official name, current tickers, former names and fiscal
year end. Brand aliases are hand-written below and reviewed by a person. Feeds the company
resolver (P3.1).

    uv run python -m finqa.ingestion.companies
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finqa.ingestion.financebench import AUDIT_PATH, DATA_DIR
from finqa.ingestion.sec import SecClient, cik10

COMPANIES_PATH = DATA_DIR / "companies.csv"
COLUMNS = [
    "company",  # FinanceBench name
    "cik",
    "ticker",  # primary ticker used in this project
    "tickers",  # current SEC tickers plus historical ones (e.g. Block: XYZ;SQ), ";"-separated
    "sec_name",
    "former_names",
    "aliases",
    "fiscal_year_end",  # MMDD, e.g. 0930
]


@dataclass(frozen=True)
class Seed:
    tickers: tuple[str, ...]  # tried in order; first is the project's primary ticker
    search: str | None = None  # SEC company-search name, for delisted companies
    aliases: tuple[str, ...] = field(default_factory=tuple)


# FinanceBench name -> how to find it, plus brand aliases (REVIEWED BY A PERSON in P1.3).
SEEDS: dict[str, Seed] = {
    "3M": Seed(("MMM",), aliases=("3M Company", "Minnesota Mining and Manufacturing")),
    "AES Corporation": Seed(("AES",), aliases=("AES", "AES Corp")),
    "AMD": Seed(("AMD",), aliases=("Advanced Micro Devices",)),
    "Activision Blizzard": Seed(
        ("ATVI",), search="activision blizzard", aliases=("Activision", "Blizzard")
    ),
    "Adobe": Seed(("ADBE",), aliases=("Adobe Inc", "Adobe Systems")),
    "Amazon": Seed(("AMZN",), aliases=("Amazon.com", "AWS")),
    "Amcor": Seed(("AMCR",), aliases=("Amcor plc",)),
    "American Express": Seed(("AXP",), aliases=("AmEx", "AMEX")),
    "American Water Works": Seed(("AWK",), aliases=("American Water",)),
    "Best Buy": Seed(("BBY",), aliases=("Best Buy Co",)),
    "Block": Seed(("XYZ", "SQ"), aliases=("Square", "Square Inc", "Block Inc", "Cash App")),
    "Boeing": Seed(("BA",), aliases=("The Boeing Company",)),
    "CVS Health": Seed(("CVS",), aliases=("CVS", "CVS Caremark")),
    "Coca-Cola": Seed(("KO",), aliases=("Coca Cola", "The Coca-Cola Company", "Coke")),
    "Corning": Seed(("GLW",), aliases=("Corning Inc",)),
    "Costco": Seed(("COST",), aliases=("Costco Wholesale",)),
    "General Mills": Seed(("GIS",), aliases=("General Mills Inc",)),
    "JPMorgan": Seed(("JPM",), aliases=("JPMorgan Chase", "JP Morgan", "Chase", "JPM")),
    "Johnson & Johnson": Seed(("JNJ",), aliases=("J&J", "Johnson and Johnson")),
    "Kraft Heinz": Seed(("KHC",), aliases=("Kraft", "Heinz", "The Kraft Heinz Company")),
    "Lockheed Martin": Seed(("LMT",), aliases=("Lockheed",)),
    "MGM Resorts": Seed(("MGM",), aliases=("MGM Resorts International", "MGM")),
    "Microsoft": Seed(("MSFT",), aliases=("Microsoft Corporation", "MSFT")),
    "Netflix": Seed(("NFLX",), aliases=("Netflix Inc",)),
    "Nike": Seed(("NKE",), aliases=("Nike Inc",)),
    "Paypal": Seed(("PYPL",), aliases=("PayPal", "PayPal Holdings")),
    "PepsiCo": Seed(("PEP",), aliases=("Pepsi", "PepsiCo Inc")),
    "Pfizer": Seed(("PFE",), aliases=("Pfizer Inc",)),
    "Ulta Beauty": Seed(("ULTA",), aliases=("Ulta", "Ulta Salon")),
    "Verizon": Seed(("VZ",), aliases=("Verizon Communications",)),
    "Walmart": Seed(("WMT",), aliases=("Wal-Mart", "Walmart Inc")),
}


class ResolutionError(ValueError):
    pass


def resolve_cik(company: str, seed: Seed, tickers: dict[str, dict[str, Any]], sec: Any) -> str:
    for t in seed.tickers:
        if t in tickers:
            return cik10(tickers[t]["cik_str"])
    if seed.search:
        matches = sec.search_company(seed.search)
        if len(matches) == 1:
            return matches[0]
        raise ResolutionError(f"{company}: search {seed.search!r} gave {len(matches)} CIKs")
    raise ResolutionError(f"{company}: none of {seed.tickers} in the SEC ticker file")


def company_row(company: str, seed: Seed, cik: str, submissions: dict[str, Any]) -> dict:
    current = [t.upper() for t in submissions.get("tickers") or []]
    former = [f["name"] for f in submissions.get("formerNames") or []]
    primary = seed.tickers[0] if seed.tickers[0] in current or not current else current[0]
    aliases = [company, *seed.aliases]
    return {
        "company": company,
        "cik": cik,
        "ticker": primary,
        "tickers": ";".join(dict.fromkeys([*current, *seed.tickers])),  # current + historical
        "sec_name": submissions["name"],
        "former_names": ";".join(former),
        "aliases": ";".join(dict.fromkeys(aliases)),
        "fiscal_year_end": submissions.get("fiscalYearEnd") or "",
    }


def build(companies: list[str], sec: Any) -> list[dict[str, Any]]:
    missing = sorted(set(companies) - SEEDS.keys())
    if missing:
        raise ResolutionError(f"no seed for: {', '.join(missing)}")
    tickers = sec.tickers()
    rows = []
    for company in sorted(companies):
        seed = SEEDS[company]
        cik = resolve_cik(company, seed, tickers, sec)
        rows.append(company_row(company, seed, cik, sec.submissions(cik)))
    ciks = [r["cik"] for r in rows]
    duplicates = {c for c in ciks if ciks.count(c) > 1}
    if duplicates:
        raise ResolutionError(f"companies share a CIK: {sorted(duplicates)}")
    return rows


def in_scope_companies(audit_path: Path = AUDIT_PATH) -> list[str]:
    with audit_path.open(encoding="utf-8", newline="") as f:
        return sorted({r["company"] for r in csv.DictReader(f) if r["in_scope"] == "True"})


def write(rows: list[dict[str, Any]], path: Path = COMPANIES_PATH) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load(path: Path = COMPANIES_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    rows = build(in_scope_companies(), SecClient())
    write(rows)
    for r in rows:
        print(f"{r['company']:<22} {r['cik']}  {r['ticker']:<5} {r['sec_name']}")
    print(f"\n{len(rows)} companies -> {COMPANIES_PATH.relative_to(DATA_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
