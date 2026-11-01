"""XBRL cache and lookup (ROADMAP P1.8): every value a company reported for a line item.

Company facts (one JSON per company, all its XBRL facts across all filings) are cached
once under data/xbrl/companyfacts/ by `SecClient.company_facts` (gitignored). A period is
identified by its actual dates, never by a filing's fiscal-year label: a 10-K's prior-year
comparatives carry the later filing's fy, and the same period reported in several filings
is how a restatement shows up. Company facts hold no dimensional (segment) facts, so every
value is a company total.

`data/metric_map.yaml` maps metric names to concepts. XBRL only helps choose an error
*type*; it never decides correctness (docs/LABELING_PROTOCOL.md).

    uv run python -m finqa.ingestion.xbrl                  # coverage + restatement candidates
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from finqa.ingestion import companies as co
from finqa.ingestion.download import MANIFEST_PATH, load_manifest
from finqa.ingestion.financebench import DATA_DIR
from finqa.ingestion.sec import XBRL_DIR, SecClient, cik10

METRIC_MAP_PATH = DATA_DIR / "metric_map.yaml"
COVERAGE_PATH = DATA_DIR / "xbrl_coverage.csv"
FACTS_DIR = XBRL_DIR / "companyfacts"
FORMS = ("10-K", "10-Q")  # restatement candidates come from periodic reports only
DURATION_SLACK_DAYS = 20  # 52/53-week years and quarters vary by about a week
_XBRL_UNITS = {"USD": "USD", "USD/share": "USD/shares", "%": "pure", "shares": "shares"}


@dataclass(frozen=True)
class Fact:
    concept: str
    unit: str  # the schema Unit ("USD", "%", ...)
    start: str | None  # ISO dates; None for instant (balance-sheet) facts
    end: str
    value: float  # full units; "%" as 21.0, not 0.21
    accession: str
    form: str
    filed: str
    fiscal_year: int | None  # the *filing's* XBRL labels, kept for reference only
    fiscal_period: str | None


@dataclass(frozen=True)
class Metric:
    name: str
    unit: str
    period: str  # "duration" or "instant"
    concepts: tuple[str, ...]


# --- Loading --------------------------------------------------------------------------------


def load_metric_map(path: Path = METRIC_MAP_PATH) -> dict[str, Metric]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        name: Metric(name, spec["unit"], spec["period"], tuple(spec["concepts"]))
        for name, spec in data.items()
    }


@cache
def _company_facts(cik: str, root: Path) -> dict[str, Any]:
    path = root / f"CIK{cik10(cik)}.json"
    if not path.exists():  # cache-first: download only what is missing
        SecClient().company_facts(cik, root=root.parent)
    return json.loads(path.read_text(encoding="utf-8"))


def facts(cik: str, concept: str, unit: str, root: Path = FACTS_DIR) -> list[Fact]:
    """Every value the company reported for a us-gaap concept in `unit`."""
    data = _company_facts(cik10(cik), root).get("facts", {}).get("us-gaap", {})
    raw = data.get(concept, {}).get("units", {}).get(_XBRL_UNITS[unit], [])
    scale = 100.0 if unit == "%" else 1.0
    return [
        Fact(
            concept=concept,
            unit=unit,
            start=f.get("start"),
            end=f["end"],
            value=round(f["val"] * scale, 9),  # 0.234 * 100 -> 23.4, not 23.400000000000002
            accession=f["accn"],
            form=f.get("form", ""),
            filed=f.get("filed", ""),
            fiscal_year=f.get("fy"),
            fiscal_period=f.get("fp"),
        )
        for f in raw
    ]


# --- Periods --------------------------------------------------------------------------------

_MONTHS = {"FY": 12, "Q1": 3, "Q2": 3, "Q3": 3, "Q4": 3, "6M": 6, "9M": 9}
_FILING = {"6M": "Q2", "9M": "Q3"}  # year-to-date periods close with that quarter's 10-Q


def duration_months(fact: Fact) -> int | None:
    """The fact's length in whole months (3, 6, 9, 12), or None for instants."""
    if fact.start is None:
        return None
    days = (dt.date.fromisoformat(fact.end) - dt.date.fromisoformat(fact.start)).days + 1
    months = round(days / 30.44)
    return months if abs(days - months * 30.44) <= DURATION_SLACK_DAYS else None


def period_end(cik: str, period: str, manifest: list[dict[str, str]] | None = None) -> str:
    """The end date of a schema Period ("FY2018", "Q3 FY2022", "9M FY2022") for a company,
    from the filing labelled with it in the manifest (fiscal labels by filing order)."""
    rows = manifest if manifest is not None else _manifest()
    head, _, year = period.rpartition(" ")
    kind = head or "FY"
    label = f"{_FILING.get(kind, kind)} {year}" if kind != "FY" else year
    for row in rows:
        if row["cik"] == cik10(cik) and row["period"] == label:
            return row["period_of_report"]
    raise KeyError(f"no filing for {period} of CIK {cik}")


@cache
def _manifest() -> list[dict[str, str]]:
    return load_manifest(MANIFEST_PATH)


def lookup(
    cik: str, concept: str, unit: str, end: str, months: int | None, root: Path = FACTS_DIR
) -> list[Fact]:
    """All values reported for one concept and period (ending `end`, lasting `months`, or
    an instant when None), across every filing, oldest filing first."""
    found = [
        f for f in facts(cik, concept, unit, root) if f.end == end and duration_months(f) == months
    ]
    return sorted(found, key=lambda f: (f.filed, f.accession))


def lookup_metric(
    cik: str,
    metric: str,
    period: str,
    metric_map: dict[str, Metric] | None = None,
    manifest: list[dict[str, str]] | None = None,
    root: Path = FACTS_DIR,
) -> list[Fact]:
    """All values reported for a metric (every mapped concept) in a schema Period. Balance-
    sheet metrics take the value at the period's end. Empty if nothing is mapped or
    reported: the verifier's "no mapping", never a failure."""
    spec = (metric_map or load_metric_map())[metric]
    end = period_end(cik, period, manifest)
    kind = period.rpartition(" ")[0] or "FY"
    months = None if spec.period == "instant" else _MONTHS[kind]
    out: list[Fact] = []
    for concept in spec.concepts:
        out.extend(lookup(cik, concept, spec.unit, end, months, root))
    return out


# --- Restatements ---------------------------------------------------------------------------


def distinct_values(found: list[Fact], tolerance: float = 0.001) -> list[float]:
    """The different values among `found`, treating values within `tolerance` (relative)
    as the same."""
    values: list[float] = []
    for f in found:
        if not any(abs(f.value - v) <= tolerance * max(abs(v), 1.0) for v in values):
            values.append(f.value)
    return values


def restatements(
    cik: str, metric_map: dict[str, Metric], since: str = "2014-01-01", root: Path = FACTS_DIR
) -> list[tuple[str, list[Fact]]]:
    """(metric, facts) for every concept and period the company reported with different
    values in different 10-K/10-Q filings: candidate restatements, for a human to check."""
    out = []
    for spec in metric_map.values():
        for concept in spec.concepts:
            by_period: dict[tuple[str | None, str], list[Fact]] = defaultdict(list)
            for f in facts(cik, concept, spec.unit, root):
                if f.form in FORMS and f.end >= since:
                    by_period[(f.start, f.end)].append(f)
            for found in by_period.values():
                if len({f.accession for f in found}) > 1 and len(distinct_values(found)) > 1:
                    out.append((spec.name, sorted(found, key=lambda f: f.filed)))
    return out


# --- Coverage report ------------------------------------------------------------------------


def coverage(metric_map: dict[str, Metric], root: Path = FACTS_DIR) -> list[dict[str, Any]]:
    """Per company: metrics with any 10-K/10-Q value since 2015, and restatement candidates."""
    rows = []
    for company in co.load():
        cik = company["cik"]
        have = [
            m.name
            for m in metric_map.values()
            if any(
                f.form in FORMS and f.end >= "2015-01-01"
                for c in m.concepts
                for f in facts(cik, c, m.unit, root)
            )
        ]
        rows.append(
            {
                "company": company["company"],
                "cik": cik,
                "metrics_reported": len(have),
                "metrics_missing": ";".join(m for m in metric_map if m not in have),
                "restatement_candidates": len(restatements(cik, metric_map, root=root)),
            }
        )
    return rows


def write_coverage(rows: list[dict[str, Any]], path: Path = COVERAGE_PATH) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    metric_map = load_metric_map()
    rows = coverage(metric_map)
    write_coverage(rows)
    print(f"{len(metric_map)} metrics, {len(rows)} companies")
    for r in rows:
        print(
            f"  {r['company']:22} {r['metrics_reported']:>2}/{len(metric_map)} metrics, "
            f"{r['restatement_candidates']} restatement candidates"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
