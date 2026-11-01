"""Quality-check review sheets (ROADMAP P1.9): one Markdown sheet per company.

Each sheet covers one 10-K, the FinanceBench 10-K most questions ask about, and shows
what a reviewer needs to compare against the filing on SEC's site:
  1. every kept section, with its first and last words (are the boundaries right?);
  2. the three financial statements plus sample tables, each with its detected unit scale
     (are tables intact, is the scale right?);
  3. sample text chunks (does the text read cleanly?).
The sheets are kept for spot checks by hand; the recorded P1.9 checks are automated
(finqa.ingestion.qa_check, data/QA_CHECKS.md). This script writes the sheets to
data/qa_sheets/.

    uv run python -m finqa.ingestion.review
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from finqa.ingestion.chunk import CHUNKS_DIR
from finqa.ingestion.download import MANIFEST_PATH, load_manifest, parse_doc_name
from finqa.ingestion.financebench import AUDIT_PATH, DATA_DIR
from finqa.ingestion.parse import SECTIONS_DIR
from finqa.schemas import Chunk

SHEETS_DIR = DATA_DIR / "qa_sheets"
TABLE_ROWS = 14  # table lines shown per sample
SAMPLE_TABLES = 4  # besides the three statements
SAMPLE_TEXT = 2
SCALE_NAMES = {1e3: "thousands", 1e6: "millions", 1e9: "billions"}

# The three statements, found by line items they always contain (first match in Item 8).
STATEMENTS = {
    # Boeing: "Net (loss)/earnings"; Microsoft and Nike: "Operations" / "Investing" headings
    "Income statement": [r"net (\(loss\)/)?(income|earnings|loss)", r"per share|diluted"],
    "Balance sheet": [r"total\s+assets", r"total liabilities|total (stockholders|shareholders)"],
    "Cash flow statement": [r"\boperat", r"\binvesting\b"],
}


def filing_url(cik: str, accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.htm"
    )


def slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")


def scale_name(scale: float | None) -> str:
    return "none" if scale is None else SCALE_NAMES.get(scale, str(scale))


# --- Choosing the filing and samples ---------------------------------------------------------


def question_counts(audit_path: Path = AUDIT_PATH) -> Counter[tuple[str, int]]:
    """In-scope FinanceBench questions per (company, fiscal year) 10-K."""
    counts: Counter[tuple[str, int]] = Counter()
    with audit_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["in_scope"] == "True":
                form, year, _ = parse_doc_name(r["doc_name"])
                if form == "10-K":
                    counts[(r["company"], year)] += 1
    return counts


def review_filings(
    manifest: list[dict[str, str]], audit_path: Path = AUDIT_PATH
) -> dict[str, dict[str, str]]:
    """Per company, the manifest row of the FinanceBench 10-K with the most in-scope
    questions (ties: the later year)."""
    best: dict[str, tuple[int, int]] = {}
    for (company, year), n in question_counts(audit_path).items():
        if company not in best or (n, year) > best[company]:
            best[company] = (n, year)
    out = {}
    for row in manifest:
        pick = best.get(row["company"])
        if pick and row["form"] == "10-K" and row["period"] == f"FY{pick[1]}":
            out[row["company"]] = row
    return out


def _lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.strip()]


def find_statements(chunks: list[Chunk]) -> dict[str, Chunk]:
    """The first Item 8 table chunk matching each statement's line items."""
    found: dict[str, Chunk] = {}
    tables = [c for c in chunks if c.is_table and c.section == "Item 8"]
    for name, patterns in STATEMENTS.items():
        for c in tables:
            text = c.text.lower()
            if all(re.search(p, text) for p in patterns) and len(_lines(c.text)) >= 10:
                found[name] = c
                break
    return found


def sample(chunks: list[Chunk], k: int, seed: str) -> list[Chunk]:
    """`k` chunks chosen reproducibly (same filing, same sample every run)."""
    if len(chunks) <= k:
        return list(chunks)
    picked = random.Random(seed).sample(range(len(chunks)), k)
    return [chunks[i] for i in sorted(picked)]


def sample_tables(chunks: list[Chunk], skip: set[str], seed: str) -> list[Chunk]:
    """Numeric tables from any section, at least one with no detected scale if any."""
    tables = [
        c
        for c in chunks
        if c.is_table and c.chunk_id not in skip and re.search(r"\d,\d{3}", c.text)
    ]
    unscaled = [c for c in tables if c.unit_scale is None]
    picked = sample(unscaled, 1, seed + "-none")
    rest = [c for c in tables if c not in picked]
    return sorted(picked + sample(rest, SAMPLE_TABLES - len(picked), seed), key=_order)


def _order(c: Chunk) -> tuple[str, int]:
    return c.section, int(c.chunk_id.rsplit("-", 1)[1])


# --- Rendering ------------------------------------------------------------------------------


def _clip(text: str, n: int, tail: bool = False) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    return "…" + text[-n:] if tail else text[:n] + "…"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def table_block(c: Chunk) -> list[str]:
    # caption lines can be Markdown headings ("### Consolidated..."): shown as plain text
    lines = [re.sub(r"^#+\s*", "", line) for line in _lines(c.text)]
    shown = lines[:TABLE_ROWS]
    more = len(lines) - len(shown)
    out = [
        f"`{c.chunk_id}` · {c.section} · detected unit scale: **{scale_name(c.unit_scale)}**",
        "",
        *shown,
    ]
    if more > 0:
        out += ["", f"*… {more} more lines*"]
    out += ["", "- [ ] table intact   - [ ] unit scale correct", ""]
    return out


def render_sheet(
    company: str, row: dict[str, str], sections: list[dict[str, Any]], chunks: list[Chunk]
) -> str:
    seed = row["accession"]
    statements = find_statements(chunks)
    tables = sample_tables(chunks, {c.chunk_id for c in statements.values()}, seed)
    texts = sample(
        [c for c in chunks if not c.is_table and c.section != "Item 8"], SAMPLE_TEXT, seed + "-text"
    )
    n_tables = sum(c.is_table for c in chunks)
    out = [
        f"# QA sheet: {company}, 10-K {row['period']}",
        "",
        f"- **Filing:** accession `{row['accession']}`, period ending {row['period_of_report']}, "
        f"filed {row['filing_date']}",
        f"- **Open it on SEC:** {filing_url(row['cik'], row['accession'])} "
        "(click the 10-K document in the first row)",
        f"- **Parsed:** {len(sections)} sections, {len(chunks) - n_tables} text chunks, "
        f"{n_tables} table chunks",
        "",
        "**How to review (about 10 minutes):** open the filing next to this sheet and check the "
        "three things below. Generated by `finqa.ingestion.review`; "
        "don't edit by hand.",
        "",
        "## 1. Sections: do they start and end at the right place?",
        "",
        "Each kept section should start at its own heading and end just before the next item.",
        "",
        "| Section | Found by | Characters | Starts with | Ends with |",
        "|---|---|---|---|---|",
    ]
    for s in sections:
        out.append(
            f"| {s['section']} | {s['method']} | {len(s['text']):,} | "
            f"{_cell(_clip(s['text'], 70))} | {_cell(_clip(s['text'], 70, tail=True))} |"
        )
    out += ["", "- [ ] all sections present, boundaries right", ""]

    out += [
        "## 2. Tables: intact, with the right unit scale?",
        "",
        "Compare each table with the same table in the filing: same rows, numbers in the "
        "right columns, nothing cut off. The unit scale should match what the filing states "
        'for that table ("in millions", "(Thousands)"); **none** is right only if the '
        "filing states no scale for it.",
        "",
    ]
    for name in STATEMENTS:
        out += [f"### {name}", ""]
        out += table_block(statements[name]) if name in statements else ["*not found*", ""]
    out += ["### Other tables (sampled)", ""]
    for c in tables:
        out += table_block(c)

    out += [
        "## 3. Text: does it read cleanly?",
        "",
        "No garbled characters, broken words, or leftover page headers and footers.",
        "",
    ]
    for c in texts:
        out += [f"`{c.chunk_id}` · {c.section}", "", f"> {_clip(c.text, 700)}", ""]
    out += ["- [ ] text reads cleanly", ""]
    return "\n".join(out)


def main() -> int:
    filings = review_filings(load_manifest(MANIFEST_PATH))
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    for company, row in sorted(filings.items()):
        sections = json.loads(
            (SECTIONS_DIR / row["cik"] / f"{row['accession']}.json").read_text(encoding="utf-8")
        )
        path = CHUNKS_DIR / row["cik"] / f"{row['accession']}.jsonl"
        chunks = [Chunk(**json.loads(x)) for x in path.read_text(encoding="utf-8").split("\n") if x]
        sheet = render_sheet(company, row, sections, chunks)
        (SHEETS_DIR / f"{slug(company)}.md").write_text(sheet, encoding="utf-8")
        found = find_statements(chunks)
        missing = [n for n in STATEMENTS if n not in found]
        print(
            f"{company:22} {row['period']}  {'missing: ' + ', '.join(missing) if missing else ''}"
        )
    print(f"{len(filings)} sheets in {SHEETS_DIR.relative_to(DATA_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
