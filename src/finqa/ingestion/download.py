"""Filing download (ROADMAP P1.4): every in-scope 10-K and 10-Q, cache-first.

Window per company: two fiscal years before its earliest FinanceBench document through one
year after its latest (docs/DECISIONS.md). Original filings only, no amendments.

For each filing, saved under data/raw/<cik>/ (gitignored):
  <accession>.md             the whole filing as Markdown (tables kept as Markdown tables)
  <accession>.sections.json  the kept sections (decision D5) as split by edgartools
The manifest data/filings_manifest.csv (committed) lists every filing with its fiscal year
and period, labelled from the order of the filings (docs/DECISIONS.md): each 10-K closes a
fiscal year and the 10-Qs before it are that year's Q1-Q3; the company's naming convention
(fiscal year named after the calendar year it ends in, or, like Ulta, the year it starts in)
is the majority of its own 10-K XBRL labels. `xbrl_label` keeps the filing's own XBRL label
and `label_source` says whether the two agree ("xbrl"), differ ("corrected"), or the filing
had none ("sequence").

    uv run python -m finqa.ingestion.download            # everything (long; resumable)
    uv run python -m finqa.ingestion.download --company 3M
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from finqa.ingestion import companies as co
from finqa.ingestion.files import save_atomic
from finqa.ingestion.financebench import AUDIT_PATH, DATA_DIR
from finqa.ingestion.sec import SecClient

RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "filings_manifest.csv"
FORMS = ("10-K", "10-Q")

# Sections kept (decision D5, docs/DECISIONS.md), as edgartools names them.
SECTIONS = {
    "10-K": ["Item 1", "Item 1A", "Item 7", "Item 7A", "Item 8"],
    "10-Q": [
        "Part I, Item 1",
        "Part I, Item 2",
        "Part I, Item 3",
        "Part I, Item 4",
        "Part II, Item 1A",
    ],
}


@dataclass(frozen=True)
class FiscalLabel:
    fiscal_year: int
    fiscal_period: str  # "FY", "Q1", "Q2", "Q3"
    source: str  # "xbrl" (agrees with the filing's XBRL), "corrected", or "sequence"

    @property
    def period(self) -> str:
        """The shared schema's Period format: "FY2022" or "Q3 FY2022"."""
        if self.fiscal_period == "FY":
            return f"FY{self.fiscal_year}"
        return f"{self.fiscal_period} FY{self.fiscal_year}"


@dataclass
class ManifestRow:
    company: str
    cik: str
    accession: str
    form: str
    fiscal_year: int
    fiscal_period: str
    period: str
    period_of_report: str
    filing_date: str
    label_source: str
    xbrl_label: str  # the filing's own XBRL label, e.g. "Q2 FY2022" ("" if none)
    markdown_path: str
    sections_path: str
    markdown_chars: int
    sections_found: str  # ";"-separated kept sections edgartools returned


MANIFEST_COLUMNS = list(ManifestRow.__dataclass_fields__)


# --- Which years and documents ------------------------------------------------------------

_DOC_NAME = re.compile(r"_(\d{4})(Q[1-4])?_(10K|10Q)$")


def parse_doc_name(doc_name: str) -> tuple[str, int, str]:
    """FinanceBench document name -> (form, fiscal year, fiscal period).

    "3M_2018_10K" -> ("10-K", 2018, "FY"); "3M_2023Q2_10Q" -> ("10-Q", 2023, "Q2").
    """
    m = _DOC_NAME.search(doc_name)
    if not m:
        raise ValueError(f"unrecognised FinanceBench document name {doc_name!r}")
    year, quarter, form = int(m.group(1)), m.group(2), m.group(3)
    return ("10-K" if form == "10K" else "10-Q"), year, quarter or "FY"


def in_scope_documents(audit_path: Path = AUDIT_PATH) -> dict[str, set[str]]:
    with audit_path.open(encoding="utf-8", newline="") as f:
        docs: dict[str, set[str]] = defaultdict(set)
        for r in csv.DictReader(f):
            if r["in_scope"] == "True":
                docs[r["company"]].add(r["doc_name"])
    return dict(docs)


def year_window(doc_names: Iterable[str]) -> tuple[int, int]:
    """Two fiscal years before the earliest document through one after the latest."""
    years = [parse_doc_name(d)[1] for d in doc_names]
    return min(years) - 2, max(years) + 1


# --- Fiscal labels ----------------------------------------------------------------------------


def xbrl_labels(company_facts: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """accession -> (fy, fp) as the filing labelled itself; the most common pair wins."""
    seen: dict[str, Counter[tuple[int, str]]] = defaultdict(Counter)
    for namespace in company_facts.get("facts", {}).values():
        for concept in namespace.values():
            for values in concept.get("units", {}).values():
                for v in values:
                    if v.get("form") in FORMS and v.get("fy") and v.get("fp"):
                        seen[v["accn"]][(int(v["fy"]), v["fp"])] += 1
    return {accn: pairs.most_common(1)[0][0] for accn, pairs in seen.items()}


def _anchor_year(period_end: dt.date) -> int:
    """Calendar year a fiscal year ends in. 52/53-week years ending in the first week of a
    month (e.g. 2021-01-02) count as ending in the previous month."""
    return (period_end - dt.timedelta(days=7)).year


def _months_between(start: dt.date, end: dt.date) -> float:
    return (end.year - start.year) * 12 + (end.month - start.month) + (end.day - start.day) / 30.4


def _period(fiscal_year: int, fiscal_period: str) -> str:
    return FiscalLabel(fiscal_year, fiscal_period, "").period


def sequence_labels(
    filings: list[tuple[str, str, dt.date]], xbrl: dict[str, tuple[int, str]]
) -> dict[str, FiscalLabel]:
    """Fiscal labels for one company's filings, given as (accession, form, period end).

    Each 10-K closes a fiscal year; a 10-Q belongs to the next 10-K after it, its quarter
    counted back from that year end (Q3 ends ~3 months before, Q1 ~9). 10-Qs after the last
    10-K belong to the year after it. The year is the 10-K's anchor year plus the company's
    offset, the majority of (XBRL fiscal year - anchor year) over its 10-Ks: 0 for most
    companies, -1 for those that name a fiscal year after the year it starts in.
    """
    tenks = sorted((end, accn) for accn, form, end in filings if form == "10-K")
    offsets = Counter(
        xbrl[accn][0] - _anchor_year(end)
        for end, accn in tenks
        if accn in xbrl and xbrl[accn][1] == "FY"
    )
    offset = offsets.most_common(1)[0][0] if offsets else 0
    year_ends = [(end, _anchor_year(end) + offset) for end, _ in tenks]

    labels: dict[str, FiscalLabel] = {}
    for accn, form, end in filings:
        if form == "10-K":
            fiscal_year, fiscal_period = _anchor_year(end) + offset, "FY"
        else:
            later = [(e, y) for e, y in year_ends if e > end]
            if later:
                year_end, fiscal_year = later[0]
            elif year_ends:
                last_end, last_year = year_ends[-1]
                year_end, fiscal_year = last_end + dt.timedelta(days=365), last_year + 1
            else:  # no 10-K at all: assume a calendar fiscal year
                year_end, fiscal_year = dt.date(end.year, 12, 31), end.year
            quarter = 4 - round(_months_between(end, year_end) / 3)
            fiscal_period = f"Q{min(3, max(1, quarter))}"
        own = xbrl.get(accn)
        if own is None:
            source = "sequence"
        elif own == (fiscal_year, fiscal_period):
            source = "xbrl"
        else:
            source = "corrected"
        labels[accn] = FiscalLabel(fiscal_year, fiscal_period, source)
    return labels


# --- Download ---------------------------------------------------------------------------------


def fetch_filing(filing: Any, markdown_path: Path, sections_path: Path, form: str) -> None:
    """Save one filing's Markdown and kept sections (skipped if both exist)."""
    if markdown_path.exists() and sections_path.exists():
        return
    sections: dict[str, str] = {}
    try:
        obj = filing.obj()
        for name in SECTIONS[form]:
            try:
                text = obj[name]
            except Exception:  # missing section: None today, SectionNotFoundError in 6.0
                text = None
            if text:
                sections[name] = text
    except Exception as e:  # structured parsing failed; P1.5 falls back to the Markdown
        sections = {"_error": f"{type(e).__name__}: {e}"}
    save_atomic(markdown_path, filing.markdown() or "")
    save_atomic(sections_path, json.dumps(sections, ensure_ascii=False))


def download_company(company: dict[str, str], doc_names: set[str], sec: SecClient) -> list:
    from edgar import Company

    first, last = year_window(doc_names)
    cik = company["cik"]
    xbrl = xbrl_labels(sec.company_facts(cik))
    # Generous filing-date range; the fiscal-year window below is the real filter.
    filings = Company(int(cik)).get_filings(form=list(FORMS), amendments=False)
    filings = filings.filter(date=f"{first - 1}-01-01:{last + 2}-12-31")
    listed = [f for f in filings if f.form in FORMS]
    labels = sequence_labels(
        [(f.accession_no, f.form, dt.date.fromisoformat(str(f.period_of_report))) for f in listed],
        xbrl,
    )
    rows = []
    for filing in listed:
        form = filing.form
        label = labels[filing.accession_no]
        if not first <= label.fiscal_year <= last:
            continue
        base = RAW_DIR / cik / filing.accession_no
        md_path, sec_path = base.with_suffix(".md"), base.with_suffix(".sections.json")
        fetch_filing(filing, md_path, sec_path, form)
        found = [k for k in json.loads(sec_path.read_text(encoding="utf-8")) if k != "_error"]
        rows.append(
            ManifestRow(
                company=company["company"],
                cik=cik,
                accession=filing.accession_no,
                form=form,
                fiscal_year=label.fiscal_year,
                fiscal_period=label.fiscal_period,
                period=label.period,
                period_of_report=str(filing.period_of_report),
                filing_date=str(filing.filing_date),
                label_source=label.source,
                xbrl_label=_period(*xbrl[filing.accession_no])
                if filing.accession_no in xbrl
                else "",
                markdown_path=md_path.relative_to(DATA_DIR.parent).as_posix(),
                sections_path=sec_path.relative_to(DATA_DIR.parent).as_posix(),
                markdown_chars=md_path.stat().st_size,
                sections_found=";".join(found),
            )
        )
    return rows


def missing_documents(docs: dict[str, set[str]], manifest: list[ManifestRow]) -> list[str]:
    """FinanceBench documents with no matching filing (company, form, fiscal year, period)."""
    have = {(r.company, r.form, r.fiscal_year, r.fiscal_period) for r in manifest}
    missing = []
    for company, names in sorted(docs.items()):
        for name in sorted(names):
            if (company, *parse_doc_name(name)) not in have:
                missing.append(f"{company}: {name}")
    return missing


def write_manifest(rows: list[ManifestRow], path: Path = MANIFEST_PATH) -> None:
    rows = sorted(rows, key=lambda r: (r.company, r.fiscal_year, r.fiscal_period, r.accession))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)


def load_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download in-scope 10-K and 10-Q filings.")
    parser.add_argument("--company", help="only this FinanceBench company (for testing)")
    args = parser.parse_args()

    from edgar import set_identity

    sec = SecClient()
    set_identity(sec.identity)
    docs = in_scope_documents()
    table = [c for c in co.load() if not args.company or c["company"] == args.company]
    rows: list[ManifestRow] = []
    for i, company in enumerate(table, 1):
        company_rows = download_company(company, docs[company["company"]], sec)
        rows += company_rows
        print(f"[{i}/{len(table)}] {company['company']}: {len(company_rows)} filings", flush=True)
    if args.company:
        print("(single company: manifest not written)")
    else:
        write_manifest(rows)
    missing = missing_documents({c["company"]: docs[c["company"]] for c in table}, rows)
    sources = Counter(r.label_source for r in rows)
    print(f"\n{len(rows)} filings; fiscal labels {dict(sources)}")
    print("FinanceBench documents missing:", missing or "none")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
