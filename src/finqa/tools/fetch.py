"""On-demand fetch tool (ROADMAP P3.3, guide §3.1): index a filing the search can't find yet.

`fetch_filing(cik, form, fiscal_year)` makes one 10-K (or, with `quarter`, one 10-Q) searchable,
reusing the Phase 1 pipeline step by step: list the company's filings on EDGAR and label their
fiscal years exactly as the download does (finqa.ingestion.download.sequence_labels), save the
filing (download.fetch_filing, plus Exhibit 13 for a 10-K), cut its sections (parse.parse_filing,
parse.complete_item8), chunk them (chunk.chunk_filing) and add the chunks to the index
(index.add_chunks). Files go where Phase 1 puts them (data/raw, data/sections, data/chunks), so
`index --sync` treats a fetched filing like any other.

If the index already has chunks for that filing, nothing is downloaded (a no-op). Only the
companies in data/companies.csv can be fetched (the resolver knows no others). The committed
manifest (data/filings_manifest.csv) is not changed.

    uv run python -m finqa.tools.fetch 0000066740 10-K 2015
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from finqa.config import BASE_CONFIG, ChunkingConfig, load_config
from finqa.ingestion import companies as co
from finqa.ingestion import download
from finqa.ingestion.chunk import CHUNKS_DIR, chunk_filing
from finqa.ingestion.files import save_atomic
from finqa.ingestion.index import add_chunks, where
from finqa.ingestion.parse import SECTIONS_DIR, complete_item8, parse_filing
from finqa.schemas import Chunk
from finqa.tools.search import FilingSearch

Status = Literal["already_indexed", "fetched", "not_found", "empty"]  # empty: no sections found


@dataclass(frozen=True)
class FetchResult:
    status: Status
    cik: str
    form: str
    period: str  # e.g. "FY2015" or "Q2 FY2016"
    accession: str | None = None
    chunks: int = 0  # chunks added to the index


def target_period(form: str, fiscal_year: int, quarter: int | None) -> str:
    if form == "10-K":
        if quarter is not None:
            raise ValueError("a 10-K covers the whole fiscal year; leave quarter out")
        return f"FY{fiscal_year}"
    if form == "10-Q":
        if quarter not in (1, 2, 3):
            raise ValueError("a 10-Q needs quarter 1, 2 or 3 (Q4 is in the 10-K)")
        return f"Q{quarter} FY{fiscal_year}"
    raise ValueError(f"form must be 10-K or 10-Q, got {form!r}")


def _edgar_filings(cik: str) -> list[Any]:
    from edgar import Company, set_identity

    from finqa.ingestion.sec import SecClient

    set_identity(SecClient().identity)
    filings = Company(int(cik)).get_filings(form=list(download.FORMS), amendments=False)
    return [f for f in filings if f.form in download.FORMS]


def _company_facts(cik: str) -> dict[str, Any]:
    from finqa.ingestion.sec import SecClient

    return SecClient().company_facts(cik)


class FilingFetcher:
    def __init__(
        self,
        search: FilingSearch,
        chunking: ChunkingConfig,
        *,
        list_filings: Callable[[str], list[Any]] = _edgar_filings,
        company_facts: Callable[[str], dict[str, Any]] = _company_facts,
        companies: list[dict[str, str]] | None = None,
        raw_dir: Path = download.RAW_DIR,
        sections_dir: Path = SECTIONS_DIR,
        chunks_dir: Path = CHUNKS_DIR,
    ) -> None:
        self.search = search
        self.chunking = chunking
        self.list_filings = list_filings
        self.company_facts = company_facts
        self.companies = {c["cik"]: c for c in (companies if companies is not None else co.load())}
        self.raw_dir = raw_dir
        self.sections_dir = sections_dir
        self.chunks_dir = chunks_dir

    def is_indexed(self, cik: str, form: str, period: str) -> bool:
        got = self.search.collection.get(
            where=where(cik=cik, form=form, period=period),  # type: ignore[arg-type]
            limit=1,
            include=[],
        )
        return bool(got["ids"])

    def fetch_filing(
        self, cik: str, form: str, fiscal_year: int, quarter: int | None = None
    ) -> FetchResult:
        period = target_period(form, fiscal_year, quarter)
        if cik not in self.companies:
            raise ValueError(f"CIK {cik} is not in data/companies.csv")
        if self.is_indexed(cik, form, period):
            return FetchResult("already_indexed", cik, form, period)

        filing = self._find(cik, form, period)
        if filing is None:
            return FetchResult("not_found", cik, form, period)
        chunks = self._process(cik, form, fiscal_year, period, filing)
        if not chunks:
            return FetchResult("empty", cik, form, period, filing.accession_no)
        add_chunks(self.search.collection, chunks, self.search.embedder)
        return FetchResult("fetched", cik, form, period, filing.accession_no, len(chunks))

    def _find(self, cik: str, form: str, period: str) -> Any | None:
        """The company's filing whose Phase 1 fiscal label is `period`."""
        listed = self.list_filings(cik)
        xbrl = download.xbrl_labels(self.company_facts(cik))
        labels = download.sequence_labels(
            [
                (f.accession_no, f.form, dt.date.fromisoformat(str(f.period_of_report)))
                for f in listed
            ],
            xbrl,
        )
        matches = [f for f in listed if f.form == form and labels[f.accession_no].period == period]
        return matches[0] if matches else None

    def _process(
        self, cik: str, form: str, fiscal_year: int, period: str, filing: Any
    ) -> list[Chunk]:
        accession = filing.accession_no
        base = self.raw_dir / cik / accession
        md_path, sec_path = base.with_suffix(".md"), base.with_suffix(".sections.json")
        download.fetch_filing(filing, md_path, sec_path, form)
        markdown = md_path.read_text(encoding="utf-8")
        sections = parse_filing(markdown, json.loads(sec_path.read_text(encoding="utf-8")), form)
        if form == "10-K":
            ex13_path = self.raw_dir / cik / f"{accession}.ex13.md"
            download.fetch_exhibit13(filing, ex13_path)
            ex13 = ex13_path.read_text(encoding="utf-8")
            sections = complete_item8(markdown, sections, ex13 or None)
        save_atomic(
            self.sections_dir / cik / f"{accession}.json",
            json.dumps([asdict(s) for s in sections], ensure_ascii=False),
        )
        meta = {
            "cik": cik,
            "ticker": self.companies[cik]["ticker"],
            "form": form,
            "fiscal_year": fiscal_year,
            "period": period,
            "accession": accession,
        }
        chunks = chunk_filing([asdict(s) for s in sections], meta, self.chunking)
        save_atomic(
            self.chunks_dir / cik / f"{accession}.jsonl",
            "".join(c.model_dump_json() + "\n" for c in chunks),
        )
        return chunks


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print("usage: python -m finqa.tools.fetch CIK FORM FISCAL_YEAR [QUARTER]")
        return 2
    cfg = load_config(BASE_CONFIG)
    fetcher = FilingFetcher(FilingSearch.open(cfg), cfg.chunking)
    quarter = int(argv[3]) if len(argv) == 4 else None
    print(fetcher.fetch_filing(argv[0], argv[1], int(argv[2]), quarter))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
