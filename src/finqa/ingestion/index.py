"""Embedding and index (ROADMAP P1.7): every chunk embedded and stored in Chroma.

Chunks are embedded with the locked model (configs/base.yaml `embedding:`), documents as
they are and queries with the model's instruction prefix, both L2-normalized, and stored in
one Chroma collection (cosine distance) under data/chroma/ (gitignored). Every Chunk field
except the text is filterable metadata (cik, ticker, form, fiscal_year, period, section,
is_table, unit_scale, source_accession); fields that are None are left out, since Chroma
can't store None. The collection records the embedding model and refuses a different one.

The build is resumable: finished filings are listed in data/chroma/indexed.txt and skipped,
and chunks are upserted by chunk ID, so an interrupted filing is simply redone.

    uv run python -m finqa.ingestion.index --limit 5      # trial on 5 filings
    uv run python -m finqa.ingestion.index                # everything (~16 hours on a laptop CPU)
    uv run python -m finqa.ingestion.index --check        # count + a sample filtered search
    uv run python -m finqa.ingestion.index --sync         # re-index filings whose chunks changed

The full build was run on a free Kaggle GPU (~20 minutes; docs/BUILD_INDEX.md):
    python -m finqa.ingestion.index --device cuda --batch-size 128 \\
        --chunks-dir <uploaded chunks> --index-dir /kaggle/working/chroma
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

import chromadb

from finqa.config import BASE_CONFIG, EmbeddingConfig, load_config
from finqa.ingestion.chunk import CHUNKS_DIR
from finqa.ingestion.download import MANIFEST_PATH, load_manifest
from finqa.ingestion.financebench import DATA_DIR
from finqa.schemas import Chunk

INDEX_DIR = DATA_DIR / "chroma"
COLLECTION = "filings"
DONE_FILE = "indexed.txt"
BATCH = 256  # chunks per Chroma upsert


class Embedder(Protocol):
    model_name: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """The locked embedding model on the CPU (needs the `embed` dependency group)."""

    def __init__(self, cfg: EmbeddingConfig, device: str = "cpu", batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = cfg.model
        self.instruction = cfg.query_instruction
        self.batch_size = batch_size
        self.model = SentenceTransformer(cfg.model, device=device)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts), batch_size=self.batch_size, normalize_embeddings=True
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode([self.instruction + text], normalize_embeddings=True)[0]
        return [float(x) for x in vector]


# --- Collection -------------------------------------------------------------------------------


def open_collection(
    model_name: str, path: Path = INDEX_DIR, client: Any = None
) -> chromadb.Collection:
    client = client or chromadb.PersistentClient(path=str(path))
    collection = client.get_or_create_collection(
        COLLECTION,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"embedding_model": model_name},
        embedding_function=None,
    )
    stored = (collection.metadata or {}).get("embedding_model")
    if stored != model_name:
        raise RuntimeError(f"index was built with {stored!r}, config says {model_name!r}")
    return collection


def metadata(chunk: Chunk) -> dict[str, Any]:
    fields = chunk.model_dump(exclude={"chunk_id", "text"})
    return {k: v for k, v in fields.items() if v is not None}


def add_chunks(collection: chromadb.Collection, chunks: list[Chunk], embedder: Embedder) -> None:
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        collection.upsert(
            ids=[c.chunk_id for c in batch],
            embeddings=embedder.embed_documents([c.text for c in batch]),  # type: ignore[arg-type]
            documents=[c.text for c in batch],
            metadatas=[metadata(c) for c in batch],  # type: ignore[misc]
        )


# --- Search -----------------------------------------------------------------------------------


def where(**filters: Any) -> dict[str, Any] | None:
    """A Chroma filter matching every given field; None-valued filters are ignored."""
    conditions = [{k: v} for k, v in filters.items() if v is not None]
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def search(
    collection: chromadb.Collection,
    embedder: Embedder,
    query: str,
    k: int,
    **filters: Any,
) -> list[Chunk]:
    """The `k` chunks nearest the query among those matching `filters` (e.g. cik=...,
    fiscal_year=2018, section="Item 8"), nearest first."""
    result = collection.query(
        query_embeddings=[embedder.embed_query(query)],  # type: ignore[arg-type]
        n_results=k,
        where=where(**filters),  # type: ignore[arg-type]
        include=["documents", "metadatas"],
    )
    ids = result["ids"][0]
    docs = (result["documents"] or [[]])[0]
    metas = (result["metadatas"] or [[]])[0]
    return [
        Chunk(
            chunk_id=i,
            text=d,
            **{"period": None, "unit_scale": None, **m},  # type: ignore[arg-type]
        )
        for i, d, m in zip(ids, docs, metas, strict=True)
    ]


# --- Build ------------------------------------------------------------------------------------


def load_chunks(cik: str, accession: str, root: Path = CHUNKS_DIR) -> list[Chunk]:
    path = root / cik / f"{accession}.jsonl"
    # split on "\n" only: splitlines() also splits on characters such as U+2028 that can
    # appear inside a chunk's text (two Block filings have them)
    lines = path.read_text(encoding="utf-8").split("\n")
    return [Chunk(**json.loads(line)) for line in lines if line]


def build(
    manifest: Iterable[dict[str, str]],
    embedder: Embedder,
    collection: chromadb.Collection,
    done_path: Path,
    chunks_root: Path = CHUNKS_DIR,
) -> int:
    """Index every filing not yet listed in `done_path`; returns the chunks added."""
    done = set(done_path.read_text(encoding="utf-8").split()) if done_path.exists() else set()
    todo = [r for r in manifest if r["accession"] not in done]
    added = 0
    started = time.monotonic()
    for n, row in enumerate(todo, 1):
        chunks = load_chunks(row["cik"], row["accession"], chunks_root)
        add_chunks(collection, chunks, embedder)
        with done_path.open("a", encoding="utf-8") as f:
            f.write(row["accession"] + "\n")
        added += len(chunks)
        elapsed = time.monotonic() - started
        eta = elapsed / n * (len(todo) - n)
        print(
            f"[{n}/{len(todo)}] {row['company']} {row['form']} {row['period']}: "
            f"{len(chunks)} chunks ({added / elapsed:.0f}/s, ~{eta / 60:.0f} min left)",
            flush=True,
        )
    return added


def sync(
    manifest: Iterable[dict[str, str]],
    embedder: Embedder,
    collection: chromadb.Collection,
    chunks_root: Path = CHUNKS_DIR,
) -> list[str]:
    """Re-index every filing whose chunk file no longer matches the index (IDs, text or
    metadata), e.g. after a parsing fix; returns their accessions. Unchanged filings are
    only compared, not re-embedded."""
    changed = []
    for row in manifest:
        chunks = load_chunks(row["cik"], row["accession"], chunks_root)
        where_filing = {"source_accession": row["accession"]}
        stored = collection.get(where=where_filing, include=["documents", "metadatas"])  # type: ignore[arg-type,list-item]
        have = {
            i: (d, m)
            for i, d, m in zip(
                stored["ids"], stored["documents"] or [], stored["metadatas"] or [], strict=True
            )
        }
        want = {c.chunk_id: (c.text, metadata(c)) for c in chunks}
        if have == want:
            continue
        changed.append(row["accession"])
        name = f"{row['company']} {row['form']} {row['period']}"
        # Same IDs and text, only metadata added or changed (e.g. a unit scale found):
        # update in place, no re-embedding. Chroma can't drop a key this way, so a removed
        # key falls through to the full re-index.
        if have.keys() == want.keys() and all(
            have[i][0] == want[i][0] and have[i][1].keys() <= want[i][1].keys() for i in want
        ):
            ids = [i for i in want if have[i][1] != want[i][1]]
            for start in range(0, len(ids), BATCH):
                batch = ids[start : start + BATCH]
                collection.update(ids=batch, metadatas=[want[i][1] for i in batch])
            print(f"updated metadata of {name}: {len(ids)} chunks")
            continue
        collection.delete(where=where_filing)  # type: ignore[arg-type]
        add_chunks(collection, chunks, embedder)
        print(f"re-indexed {name}: {len(chunks)} chunks")
    return changed


def check(collection: chromadb.Collection, embedder: Embedder) -> None:
    """The index size, and a filtered search on a FinanceBench question (3M FY2018 capex)."""
    print(f"the index holds {collection.count()} chunks")
    hits = search(
        collection,
        embedder,
        "What is 3M's FY2018 capital expenditure?",
        k=3,
        cik="0000066740",
        fiscal_year=2018,
        form="10-K",
        section="Item 8",
    )
    for h in hits:
        first = next((line for line in h.text.split("\n") if line.strip()), "")
        print(f"  {h.chunk_id} (unit_scale {h.unit_scale}): {first[:90]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, help="index only the first N remaining filings")
    parser.add_argument("--company", help="only this FinanceBench company name")
    parser.add_argument("--device", default="cpu", help="cpu, or cuda on a GPU machine")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--chunks-dir", type=Path, default=CHUNKS_DIR)
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    parser.add_argument("--check", action="store_true", help="only check the built index")
    parser.add_argument(
        "--sync", action="store_true", help="re-index filings whose chunks changed since"
    )
    args = parser.parse_args()

    cfg = load_config(BASE_CONFIG).embedding
    embedder = SentenceTransformerEmbedder(cfg, args.device, args.batch_size)
    collection = open_collection(cfg.model, args.index_dir)
    if args.check:
        check(collection, embedder)
        return 0
    manifest = load_manifest(MANIFEST_PATH)
    if args.company:
        manifest = [r for r in manifest if r["company"] == args.company]
    if args.sync:
        changed = sync(manifest, embedder, collection, args.chunks_dir)
        print(f"{len(changed)} filings re-indexed; the index holds {collection.count()}")
        return 0
    done_path = args.index_dir / DONE_FILE
    if args.limit:
        done = set(done_path.read_text().split()) if done_path.exists() else set()
        manifest = [r for r in manifest if r["accession"] not in done][: args.limit]
    added = build(manifest, embedder, collection, done_path, args.chunks_dir)
    print(f"added {added} chunks; the index now holds {collection.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
