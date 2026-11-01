"""Index build and filtered search with a fake embedder in a temporary Chroma. No network."""

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from finqa.ingestion.index import build, metadata, open_collection, search, where
from finqa.schemas import Chunk


class FakeEmbedder:
    """Bag of hashed words: chunks sharing words with the query are nearest."""

    model_name = "fake-model"

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * 64
        for word in text.lower().split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def chunk(cik: str, year: int, section: str, i: int, text: str, scale: float | None) -> Chunk:
    accession = f"{cik}-{year}"
    return Chunk(
        chunk_id=f"{cik}-{accession}-{section.lower().replace(' ', '-')}-{i}",
        cik=cik,
        ticker={"0000066740": "MMM", "0000320193": "AAPL"}[cik],
        form="10-K",
        fiscal_year=year,
        period=f"FY{year}",
        section=section,
        is_table=scale is not None,
        unit_scale=scale,
        text=text,
        source_accession=accession,
    )


CHUNKS = [
    chunk(cik, year, section, i, f"capital expenditures purchases of property {cik} {year}", s)
    for cik in ("0000066740", "0000320193")
    for year in (2018, 2019)
    for section in ("Item 7", "Item 8")
    for i, s in enumerate([None, 1e6])
]


@pytest.fixture
def chunks_root(tmp_path: Path) -> Path:
    root = tmp_path / "chunks"
    for c in CHUNKS:
        path = root / c.cik / f"{c.source_accession}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(c.model_dump_json() + "\n")
    return root


def manifest() -> list[dict[str, str]]:
    accessions = sorted({(c.cik, c.source_accession) for c in CHUNKS})
    return [
        {"company": "X", "form": "10-K", "period": "FY", "cik": cik, "accession": acc}
        for cik, acc in accessions
    ]


def built(tmp_path: Path, chunks_root: Path):  # type: ignore[no-untyped-def]
    collection = open_collection("fake-model", tmp_path / "chroma")
    added = build(manifest(), FakeEmbedder(), collection, tmp_path / "done.txt", chunks_root)
    return collection, added


def test_filtered_query_returns_only_matching_chunks(tmp_path: Path, chunks_root: Path) -> None:
    collection, added = built(tmp_path, chunks_root)
    assert added == len(CHUNKS) == collection.count()
    hits = search(
        collection,
        FakeEmbedder(),
        "capital expenditures",
        k=10,
        cik="0000066740",
        fiscal_year=2018,
        section="Item 8",
    )
    assert len(hits) == 2  # the table and the text chunk of that one section
    assert all((h.cik, h.fiscal_year, h.section) == ("0000066740", 2018, "Item 8") for h in hits)
    tables = search(collection, FakeEmbedder(), "capital", k=50, is_table=True, ticker="AAPL")
    assert len(tables) == 4 and all(h.is_table and h.ticker == "AAPL" for h in tables)


def test_search_returns_the_stored_chunk_unchanged(tmp_path: Path, chunks_root: Path) -> None:
    collection, _ = built(tmp_path, chunks_root)
    by_id = {c.chunk_id: c for c in CHUNKS}
    for hit in search(collection, FakeEmbedder(), "property", k=len(CHUNKS)):
        assert hit == by_id[hit.chunk_id]  # including unit_scale=None, which Chroma can't store


def test_build_is_resumable(tmp_path: Path, chunks_root: Path) -> None:
    collection, _ = built(tmp_path, chunks_root)
    again = build(manifest(), FakeEmbedder(), collection, tmp_path / "done.txt", chunks_root)
    assert again == 0 and collection.count() == len(CHUNKS)


def test_load_chunks_keeps_unicode_line_separators_in_text(tmp_path: Path) -> None:
    from finqa.ingestion.index import load_chunks

    chunk = CHUNKS[0].model_copy(update={"text": "Revenue grew\x85 strongly"})
    path = tmp_path / chunk.cik / f"{chunk.source_accession}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(chunk.model_dump_json() + "\n", encoding="utf-8")
    assert load_chunks(chunk.cik, chunk.source_accession, tmp_path) == [chunk]


def test_index_refuses_a_different_embedding_model(tmp_path: Path) -> None:
    open_collection("fake-model", tmp_path / "chroma")
    with pytest.raises(RuntimeError, match="fake-model"):
        open_collection("another-model", tmp_path / "chroma")


def test_where_and_metadata() -> None:
    assert where() is None and where(cik=None) is None
    assert where(cik="1") == {"cik": "1"}
    assert where(cik="1", fiscal_year=2018) == {"$and": [{"cik": "1"}, {"fiscal_year": 2018}]}
    assert "unit_scale" not in metadata(CHUNKS[0]) and metadata(CHUNKS[1])["unit_scale"] == 1e6
