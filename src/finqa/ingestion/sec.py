"""Minimal SEC EDGAR client: identity header, polite rate limit, cache-first.

The SEC requires a User-Agent naming the requester (EDGAR_IDENTITY in .env) and allows at
most 10 requests per second. Every response is cached under data/sec/ (gitignored), so a
rerun never re-downloads.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from finqa.config import CONFIGS_DIR, Secrets
from finqa.ingestion.files import save_atomic

CACHE_DIR = CONFIGS_DIR.parent / "data" / "sec"
XBRL_DIR = CONFIGS_DIR.parent / "data" / "xbrl"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEARCH_URL = "https://www.sec.gov/cgi-bin/browse-edgar"


def cik10(cik: int | str) -> str:
    """CIKs are written zero-padded to 10 digits in SEC URLs and in this project."""
    return f"{int(cik):010d}"


class SecClient:
    MIN_INTERVAL_S = 0.15  # stays well under the SEC's 10 requests per second

    def __init__(
        self,
        identity: str | None = None,
        cache_dir: Path = CACHE_DIR,
        http: httpx.Client | None = None,
    ) -> None:
        identity = identity or Secrets().edgar_identity
        if not identity:
            raise RuntimeError("EDGAR_IDENTITY is not set (see .env.example)")
        self.identity = identity
        self.cache_dir = cache_dir
        self._http = http or httpx.Client(headers={"User-Agent": identity}, timeout=60)
        self._last = 0.0

    def _get(self, url: str, params: dict[str, str] | None = None) -> str:
        wait = self.MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        response = self._http.get(url, params=params, follow_redirects=True)
        self._last = time.monotonic()
        response.raise_for_status()
        return response.text

    def cached_text(
        self,
        name: str,
        url: str,
        params: dict[str, str] | None = None,
        root: Path | None = None,
    ) -> str:
        path = (root or self.cache_dir) / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        text = self._get(url, params)
        save_atomic(path, text)
        return text

    def tickers(self) -> dict[str, dict[str, Any]]:
        """Current SEC ticker file, keyed by ticker: {cik_str, ticker, title}."""
        data = json.loads(self.cached_text("company_tickers.json", TICKERS_URL))
        return {v["ticker"].upper(): v for v in data.values()}

    def submissions(self, cik: int | str) -> dict[str, Any]:
        """Company metadata: name, tickers, formerNames, fiscalYearEnd, recent filings."""
        c = cik10(cik)
        url = SUBMISSIONS_URL.format(cik=c)
        return json.loads(self.cached_text(f"submissions/CIK{c}.json", url))

    def company_facts(self, cik: int | str, root: Path = XBRL_DIR) -> dict[str, Any]:
        """Every XBRL fact the company has reported (ROADMAP P1.8 builds the lookup on it).
        Each value carries the filing's accession and its fiscal year / period labels."""
        c = cik10(cik)
        url = COMPANY_FACTS_URL.format(cik=c)
        return json.loads(self.cached_text(f"companyfacts/CIK{c}.json", url, root=root))

    def search_company(self, name: str) -> list[str]:
        """CIKs of companies matching `name` that have filed 10-Ks (for delisted companies)."""
        params = {
            "company": name,
            "type": "10-K",
            "owner": "include",
            "count": "40",
            "action": "getcompany",
            "output": "atom",
        }
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        text = self.cached_text(f"search/{slug}.xml", SEARCH_URL, params)
        return sorted({cik10(c) for c in re.findall(r"<cik>(\d+)</cik>", text)})
