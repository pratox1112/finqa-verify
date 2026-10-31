"""Chunking and unit scale (ROADMAP P1.6): each parsed section as retrieval chunks.

  - Text: paragraphs packed into chunks of at most `text_max_tokens`, cut on paragraph
    boundaries (a paragraph that is too long alone is cut on sentences), with about
    `overlap_tokens` of the previous chunk's closing sentences repeated at the start.
  - Tables: one chunk per table, with its caption (up to two short lines just above it).
    A table over `table_max_tokens` is split into row groups, each repeating the caption
    and the header row. Single-column tables (headings laid out as tables) count as text.
  - unit_scale: from "(in millions)", "(Millions)", "in thousands, except per share", etc.
    in the table's header row, else its caption, else its first row. None when nothing is
    stated; it is never guessed (docs/DECISIONS.md). "Except per share" figures keep the
    table's scale here; the verifier handles them.
  - Chunk IDs: {cik}-{accession}-{section}-{index}, e.g. "0000066740-0001558370-17-000479-
    item-7-12", numbered within the section (text chunks, then tables in order), so a
    rerun gives the same IDs.

Sizes come from the `chunking:` section of configs/base.yaml. Tokens are counted as words
plus punctuation marks, close to the embedding model's own tokenizer for filing text.
Output per filing: data/chunks/<cik>/<accession>.jsonl (gitignored); counts per company:
data/chunk_stats.csv (committed).

    uv run python -m finqa.ingestion.chunk
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finqa.config import BASE_CONFIG, ChunkingConfig, load_config
from finqa.ingestion import companies as co
from finqa.ingestion.download import MANIFEST_PATH, load_manifest
from finqa.ingestion.files import save_atomic
from finqa.ingestion.financebench import DATA_DIR
from finqa.ingestion.parse import SECTIONS_DIR
from finqa.schemas import Chunk

CHUNKS_DIR = DATA_DIR / "chunks"
STATS_PATH = DATA_DIR / "chunk_stats.csv"
CAPTION_LINES = 2
CAPTION_MAX_CHARS = 400  # of a longer line above a table, only its last sentence is caption

_TOKEN = re.compile(r"\w+|[^\w\s]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"$])")
_SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


# --- Unit scale -------------------------------------------------------------------------------

SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
# "(in millions, except per share data)", "(millions of dollars)", "($ in thousands)",
# "dollars in millions", or a header cell that is just "Millions" / "$ millions".
_SCALE_PHRASES = [
    re.compile(r"\(\s*(?:[$\w.]+\s+){0,3}?(thousand|million|billion)s?\b[^()]*\)", re.I),
    re.compile(r"\bin\s+(thousand|million|billion)s\b", re.I),
    re.compile(r"^\W*(?:\$|usd|dollars)?\s*(thousand|million|billion)s\W*$", re.I),
]


def detect_scale(text: str) -> float | None:
    for pattern in _SCALE_PHRASES:
        m = pattern.search(text)
        if m:
            return SCALES[m.group(1).lower()]
    return None


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table_scale(caption: list[str], rows: list[str]) -> float | None:
    """The scale a table states: in its header row, else its caption, else its first row."""
    header, body = _split_header(rows)
    candidates = [c for row in header if not _SEPARATOR.match(row) for c in _cells(row)]
    for text in [*candidates, " ".join(caption), *(_cells(body[0]) if body else [])]:
        scale = detect_scale(text)
        if scale is not None:
            return scale
    return None


# --- Blocks: paragraphs and tables ------------------------------------------------------------


@dataclass
class Table:
    caption: list[str]
    rows: list[str]


def blocks(text: str) -> list[str | Table]:
    """The section in order: text paragraphs (str) and tables. A table's caption lines stay
    in the text too, so the prose reads the same."""
    out: list[str | Table] = []
    lines = text.split("\n")
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append("\n".join(paragraph).strip())
            paragraph.clear()

    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            if lines[i].strip():
                paragraph.append(lines[i])
            else:
                flush()
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        rows = [r.strip() for r in lines[i:j]]
        if all(len(_cells(r)) == 1 for r in rows if not _SEPARATOR.match(r)):
            # single-column: a heading or note laid out as a table
            flush()
            cells = [_cells(r)[0] for r in rows if not _SEPARATOR.match(r)]
            out.append("\n".join(c for c in cells if c))
        else:
            caption: list[str] = []
            for line in reversed(lines[:i]):
                if not line.strip():
                    if caption:
                        break
                    continue
                if line.lstrip().startswith("|"):
                    break
                if len(line) > CAPTION_MAX_CHARS:
                    # prose ending in "...as follows (in thousands):": its last sentence
                    last = _SENTENCE.split(line.strip())[-1]
                    if len(last) <= CAPTION_MAX_CHARS:
                        caption.insert(0, last)
                    break
                caption.insert(0, line.strip())
                if len(caption) == CAPTION_LINES:
                    break
            flush()
            out.append(Table(caption, rows))
        i = j
    flush()
    return [b for b in out if isinstance(b, Table) or b]


# --- Text chunks ------------------------------------------------------------------------------


@dataclass
class _Piece:
    text: str
    paragraph: int  # pieces of the same paragraph are joined with a space


def _split_long(text: str, max_tokens: int) -> list[str]:
    """Sentences, and a sentence still over the limit cut into runs of words."""
    out: list[str] = []
    for sentence in _SENTENCE.split(text):
        if count_tokens(sentence) <= max_tokens:
            out.append(sentence)
            continue
        words: list[str] = []
        for word in sentence.split():
            if words and count_tokens(" ".join([*words, word])) > max_tokens:
                out.append(" ".join(words))
                words = []
            words.append(word)
        if words:
            out.append(" ".join(words))
    return out


def _join(pieces: list[_Piece]) -> str:
    text = ""
    for k, p in enumerate(pieces):
        if k:
            text += " " if p.paragraph == pieces[k - 1].paragraph else "\n\n"
        text += p.text
    return text


def _overlap(pieces: list[_Piece], max_tokens: int) -> list[_Piece]:
    """The closing sentences of a chunk, up to `max_tokens`, to open the next one."""
    out: list[_Piece] = []
    total = 0
    for p in reversed(pieces):
        for sentence in reversed(_SENTENCE.split(p.text)):
            n = count_tokens(sentence)
            if total + n > max_tokens:
                return out
            out.insert(0, _Piece(sentence, p.paragraph))
            total += n
    return out


def text_chunks(paragraphs: list[str], cfg: ChunkingConfig) -> list[str]:
    pieces: list[_Piece] = []
    for k, para in enumerate(paragraphs):
        if count_tokens(para) <= cfg.text_max_tokens:
            pieces.append(_Piece(para, k))
        else:
            pieces.extend(_Piece(s, k) for s in _split_long(para, cfg.text_max_tokens))
    chunks: list[str] = []
    current: list[_Piece] = []
    tokens = 0
    for piece in pieces:
        n = count_tokens(piece.text)
        if current and tokens + n > cfg.text_max_tokens:
            chunks.append(_join(current))
            current = _overlap(current, cfg.overlap_tokens)
            tokens = sum(count_tokens(p.text) for p in current)
            if tokens + n > cfg.text_max_tokens:
                current, tokens = [], 0
        current.append(piece)
        tokens += n
    if current:
        chunks.append(_join(current))
    return chunks


# --- Table chunks -----------------------------------------------------------------------------


def _split_header(rows: list[str]) -> tuple[list[str], list[str]]:
    """Header row (plus the |---| line after it), and the body rows."""
    n = 2 if len(rows) > 1 and _SEPARATOR.match(rows[1]) else 1
    return rows[:n], rows[n:]


def table_chunks(table: Table, max_tokens: int) -> list[str]:
    """The table with its caption; if too long, row groups that each repeat the caption
    and the header."""
    head = "\n".join(table.caption) + "\n\n" if table.caption else ""
    whole = head + "\n".join(table.rows)
    if count_tokens(whole) <= max_tokens:
        return [whole]
    header, body = _split_header(table.rows)
    fixed = count_tokens(head) + sum(count_tokens(r) for r in header)
    if fixed > max_tokens // 2:
        # a header too big to repeat (a paragraph merged into the table): plain rows
        head, header, body = "", [], table.caption + table.rows
        fixed = 0
    rows: list[str] = []
    for row in body:  # a row still over the limit is cut into runs of words
        too_long = count_tokens(row) > max_tokens - fixed
        rows.extend(_split_long(row, max_tokens - fixed) if too_long else [row])
    groups: list[list[str]] = []
    group: list[str] = []
    tokens = fixed
    for row in rows:
        n = count_tokens(row)
        if group and tokens + n > max_tokens:
            groups.append(group)
            group, tokens = [], fixed
        group.append(row)
        tokens += n
    groups.append(group)
    return [head + "\n".join(header + g) for g in groups]


# --- Per filing -------------------------------------------------------------------------------


def section_slug(section: str) -> str:
    """ "Part I, Item 2" -> "part-i-item-2"; "Item 1A" -> "item-1a"."""
    return re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")


def chunk_section(
    section: str, text: str, meta: dict[str, Any], cfg: ChunkingConfig
) -> list[Chunk]:
    """Chunks of one section, text chunks first, then tables in order. `meta` holds the
    filing's cik, ticker, form, fiscal_year, period and accession."""
    parts = blocks(text)
    items: list[tuple[str, bool, float | None]] = [
        (t, False, None) for t in text_chunks([b for b in parts if isinstance(b, str)], cfg)
    ]
    for b in parts:
        if isinstance(b, Table):
            scale = table_scale(b.caption, b.rows)
            items.extend((t, True, scale) for t in table_chunks(b, cfg.table_max_tokens))
    prefix = f"{meta['cik']}-{meta['accession']}-{section_slug(section)}"
    return [
        Chunk(
            chunk_id=f"{prefix}-{i}",
            cik=meta["cik"],
            ticker=meta["ticker"],
            form=meta["form"],
            fiscal_year=int(meta["fiscal_year"]),
            period=meta["period"] or None,
            section=section,
            is_table=is_table,
            unit_scale=scale,
            text=chunk_text,
            source_accession=meta["accession"],
        )
        for i, (chunk_text, is_table, scale) in enumerate(items)
    ]


def chunk_filing(
    sections: list[dict[str, Any]], meta: dict[str, Any], cfg: ChunkingConfig
) -> list[Chunk]:
    return [c for s in sections for c in chunk_section(s["section"], s["text"], meta, cfg)]


def run(manifest: list[dict[str, str]], cfg: ChunkingConfig) -> list[dict[str, Any]]:
    tickers = {r["cik"]: r["ticker"] for r in co.load()}
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in manifest:
        path = SECTIONS_DIR / row["cik"] / f"{row['accession']}.json"
        sections = json.loads(path.read_text(encoding="utf-8"))
        meta = {**row, "ticker": tickers[row["cik"]]}
        chunks = chunk_filing(sections, meta, cfg)
        out = CHUNKS_DIR / row["cik"] / f"{row['accession']}.jsonl"
        save_atomic(out, "".join(c.model_dump_json() + "\n" for c in chunks))
        s = stats[row["company"]]
        s["filings"] += 1
        for c in chunks:
            s["table_chunks" if c.is_table else "text_chunks"] += 1
        for sec in sections:
            for b in blocks(sec["text"]):
                if isinstance(b, Table):
                    s["tables"] += 1
                    s["tables_split"] += len(table_chunks(b, cfg.table_max_tokens)) > 1
                    s["tables_with_scale"] += table_scale(b.caption, b.rows) is not None
    rows = []
    for company in sorted(stats):
        s = stats[company]
        rows.append(
            {
                "company": company,
                "filings": s["filings"],
                "text_chunks": s["text_chunks"],
                "table_chunks": s["table_chunks"],
                "tables": s["tables"],
                "tables_split": s["tables_split"],
                "tables_with_scale": s["tables_with_scale"],
                "scale_rate": round(s["tables_with_scale"] / max(1, s["tables"]), 3),
            }
        )
    return rows


def write_stats(rows: list[dict[str, Any]], path: Path = STATS_PATH) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    cfg = load_config(BASE_CONFIG).chunking
    rows = run(load_manifest(MANIFEST_PATH), cfg)
    write_stats(rows)
    total: Counter[str] = Counter()
    for r in rows:
        for k in ("filings", "text_chunks", "table_chunks", "tables", "tables_split"):
            total[k] += int(r[k])
        total["tables_with_scale"] += int(r["tables_with_scale"])
    rate = total["tables_with_scale"] / max(1, total["tables"])
    print(f"{dict(total)}; unit scale stated on {rate:.1%} of tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
