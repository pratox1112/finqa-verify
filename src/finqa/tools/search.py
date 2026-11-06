"""Filing search tool (ROADMAP P3.2): filtered semantic search over the indexed filings.

`search_filings(cik, fiscal_year, section, query)` returns the top-k chunks (configs/base.yaml
`retrieval.top_k`) nearest the query among those matching every filter that is set; a filter
left as None is not applied. Each returned Chunk carries its chunk_id, which generators cite
in their claims and the agent adds to its evidence.

    uv run python -m finqa.tools.search 0000066740 2018 "Item 8" "capital expenditures"
"""

from __future__ import annotations

import sys
from typing import Any

import chromadb

from finqa.config import BASE_CONFIG, Config, load_config
from finqa.ingestion.index import Embedder, SentenceTransformerEmbedder, open_collection, search
from finqa.schemas import Chunk


class FilingSearch:
    def __init__(self, collection: chromadb.Collection, embedder: Embedder, top_k: int) -> None:
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        self.collection = collection
        self.embedder = embedder
        self.top_k = top_k

    @classmethod
    def open(cls, cfg: Config, **embedder_kwargs: Any) -> FilingSearch:
        """The built index under data/chroma/ with the locked embedding model."""
        embedder = SentenceTransformerEmbedder(cfg.embedding, **embedder_kwargs)
        return cls(open_collection(cfg.embedding.model), embedder, cfg.retrieval.top_k)

    def search_filings(
        self,
        cik: str | None,
        fiscal_year: int | None,
        section: str | None,
        query: str,
        *,
        form: str | None = None,  # "10-K" | "10-Q"
        period: str | None = None,  # e.g. "Q2 FY2023"
        is_table: bool | None = None,  # True: tables only; False: text only
        k: int | None = None,
    ) -> list[Chunk]:
        """Nearest chunks first. `section` is as stored, e.g. "Item 8" or "Part I, Item 1"."""
        if not query.strip():
            raise ValueError("query is empty")
        return search(
            self.collection,
            self.embedder,
            query,
            k or self.top_k,
            cik=cik,
            fiscal_year=fiscal_year,
            section=section,
            form=form,
            period=period,
            is_table=is_table,
        )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: python -m finqa.tools.search CIK FISCAL_YEAR SECTION QUERY")
        return 2
    cik, year, section, query = argv
    tool = FilingSearch.open(load_config(BASE_CONFIG))
    for c in tool.search_filings(cik, int(year), section or None, query):
        first = next((line for line in c.text.split("\n") if line.strip()), "")
        print(f"{c.chunk_id} ({c.form} {c.period}, {c.section}): {first[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
