"""Company resolver (ROADMAP P3.1): a company name, brand or ticker to one SEC CIK.

Matches against every name in data/companies.csv: the FinanceBench name, the SEC name,
former names (Facebook for Meta, Square for Block), brand aliases, and tickers (every share
class and historical ticker). Names are compared after normalization (case, punctuation,
"&" vs "and", legal suffixes such as Inc or Corp, and share-class words such as "Class A"),
scored with rapidfuzz's WRatio (0-100). A ticker or a name that is equal after
normalization scores 100.

The best company is returned only if it scores at least `threshold` and leads the next
company by at least `margin` (configs/base.yaml `retrieval.resolver_*`). Otherwise the
result carries no company, only the ranked candidates, so a caller never silently gets a
guess: "American" is both American Express and American Water Works.

    uv run python -m finqa.tools.resolver "Facebook" "GOOG" "American"
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from finqa.config import BASE_CONFIG, load_config
from finqa.ingestion.companies import COMPANIES_PATH, load

MAX_CANDIDATES = 5

# Words that don't tell companies apart: legal forms and share classes.
_DROP = {
    "the",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "plc",
    "ltd",
    "llc",
    "holdings",
}
_SHARE_CLASS = re.compile(r"\b(class|series)\s+[a-z]\b")


def normalize(name: str) -> str:
    """'The Coca-Cola Company' -> 'coca cola'; 'Alphabet Inc. Class C' -> 'alphabet'."""
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _SHARE_CLASS.sub(" ", text)
    return " ".join(w for w in text.split() if w not in _DROP)


@dataclass(frozen=True)
class Company:
    name: str  # FinanceBench name
    cik: str
    ticker: str  # primary ticker
    tickers: tuple[str, ...]
    sec_name: str
    former_names: tuple[str, ...]
    aliases: tuple[str, ...]
    fiscal_year_end: str  # MMDD

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Company:
        def split(field: str) -> tuple[str, ...]:
            return tuple(x for x in row[field].split(";") if x)

        return cls(
            name=row["company"],
            cik=row["cik"],
            ticker=row["ticker"],
            tickers=split("tickers"),
            sec_name=row["sec_name"],
            former_names=split("former_names"),
            aliases=split("aliases"),
            fiscal_year_end=row["fiscal_year_end"],
        )

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, self.sec_name, *self.former_names, *self.aliases)


@dataclass(frozen=True)
class Candidate:
    company: Company
    score: float
    matched: str  # the name or ticker that scored best


@dataclass(frozen=True)
class Resolution:
    query: str
    company: Company | None  # None: no single confident match
    candidates: tuple[Candidate, ...]  # best first, one per company

    @property
    def resolved(self) -> bool:
        return self.company is not None


class CompanyResolver:
    def __init__(self, companies: Iterable[Company], threshold: float, margin: float) -> None:
        self.companies = list(companies)
        self.threshold = threshold
        self.margin = margin
        self._names = [[(n, normalize(n)) for n in c.names if normalize(n)] for c in self.companies]

    @classmethod
    def from_csv(cls, path: Path = COMPANIES_PATH, config: Path = BASE_CONFIG) -> CompanyResolver:
        r = load_config(config).retrieval
        return cls(
            [Company.from_row(row) for row in load(path)], r.resolver_threshold, r.resolver_margin
        )

    def _score(self, i: int, query: str, normalized: str) -> Candidate:
        company = self.companies[i]
        if query.strip().upper() in company.tickers:
            return Candidate(company, 100.0, query.strip().upper())
        best = Candidate(company, 0.0, "")
        for name, norm in self._names[i]:
            score = 100.0 if norm == normalized else fuzz.WRatio(normalized, norm)
            if score > best.score:
                best = Candidate(company, score, name)
        return best

    def resolve(self, name: str) -> Resolution:
        normalized = normalize(name)
        ranked = sorted(
            (self._score(i, name, normalized) for i in range(len(self.companies))),
            key=lambda c: -c.score,
        )
        top = ranked[:MAX_CANDIDATES]
        if not top or not normalized and top[0].score < 100:
            return Resolution(name, None, tuple(top))
        runner_up = ranked[1].score if len(ranked) > 1 else 0.0
        confident = top[0].score >= self.threshold and top[0].score - runner_up >= self.margin
        return Resolution(name, top[0].company if confident else None, tuple(top))


def main(argv: list[str]) -> int:
    resolver = CompanyResolver.from_csv()
    for name in argv:
        result = resolver.resolve(name)
        head = f"{result.company.name} ({result.company.cik})" if result.company else "ambiguous"
        print(f"{name!r}: {head}")
        for c in result.candidates[:3]:
            print(f"    {c.score:5.1f}  {c.company.name:<22} via {c.matched!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
