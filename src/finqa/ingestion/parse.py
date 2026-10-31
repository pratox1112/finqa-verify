"""Section parsing (ROADMAP P1.5): each filing's kept sections as clean Markdown.

edgartools splits filings into items reliably but returns them as plain text, which
flattens tables. So each section is cut from the filing's Markdown (tables intact):

  1. "edgartools": the edgartools section's opening and closing words are located in the
     Markdown (comparing letters and digits only, so formatting doesn't matter);
  2. "heading" (fallback, logged): where edgartools has no section or its words can't be
     found, the section runs from its own heading ("Item 7." at the start of a line, not in
     a table) to the next item heading.

Markdown escapes are removed ("capital\\." -> "capital."), except escaped pipes, which
keep tables intact. Output per filing: data/sections/<cik>/<accession>.json (gitignored);
fallback and missing counts per company: data/parse_stats.csv (committed).

    uv run python -m finqa.ingestion.parse
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from finqa.ingestion.download import MANIFEST_PATH, SECTIONS, load_manifest
from finqa.ingestion.files import save_atomic
from finqa.ingestion.financebench import DATA_DIR

SECTIONS_DIR = DATA_DIR / "sections"
STATS_PATH = DATA_DIR / "parse_stats.csv"
ANCHOR = 120  # letters/digits matched at each end of an edgartools section

# Every item heading that can follow a kept section, so a heading-based section knows where
# it ends. Ordered as they appear in the form.
ALL_ITEMS = {
    "10-K": [
        "1",
        "1A",
        "1B",
        "1C",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "7A",
        "8",
        "9",
        "9A",
        "9B",
        "9C",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
    ],
    "10-Q": ["1", "2", "3", "4", "1A", "5", "6"],  # Part I 1-4, then Part II 1, 1A, 2-6
}


@dataclass
class Section:
    section: str  # edgartools name, e.g. "Item 7" or "Part I, Item 2"
    method: str  # "edgartools" or "heading"
    start: int  # character offsets in the filing's Markdown
    end: int
    text: str


# --- Text helpers -----------------------------------------------------------------------------

_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~:$&%'\"=<^,;?@/])")


def unescape(markdown: str) -> str:
    """Remove Markdown backslash escapes, keeping "\\|" so table cells stay separate."""
    return _ESCAPE.sub(r"\1", markdown)


def normalize(text: str) -> tuple[str, list[int]]:
    """Lowercase letters and digits only, with each kept character's index in `text`."""
    chars, index = [], []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            index.append(i)
    return "".join(chars), index


# --- Method 1: locate an edgartools section in the Markdown -----------------------------------

PROBE = 40  # letters/digits used to find candidate starts
_GRAM = 8


def _grams(text: str) -> set[str]:
    return {text[i : i + _GRAM] for i in range(0, max(0, len(text) - _GRAM + 1), 2)}


def _best_start(sec_norm: str, md_norm: str) -> int | None:
    """Where the section starts in the normalized Markdown. The opening words can appear
    several times (table of contents, cross-references), so each occurrence is scored by
    how much of the section's next 3,000 characters follows it. If the opening sits in a
    table laid out differently, later probes are tried and the start is backed up."""
    reference = _grams(sec_norm[:3000])
    for offset in range(0, min(len(sec_norm) - PROBE, 400) + 1, PROBE):
        probe = sec_norm[offset : offset + PROBE]
        candidates: list[int] = []
        at = md_norm.find(probe)
        while at >= 0 and len(candidates) < 50:
            candidates.append(at)
            at = md_norm.find(probe, at + 1)
        if candidates:
            best = max(candidates, key=lambda c: len(_grams(md_norm[c : c + 3000]) & reference))
            return max(0, best - offset)
    return None


def locate(section_text: str, md_norm: str, md_index: list[int]) -> tuple[int, int] | None:
    """(start, end) offsets in the Markdown of the span matching `section_text`, or None."""
    sec_norm, _ = normalize(section_text)
    if len(sec_norm) < PROBE:
        return None
    start = _best_start(sec_norm, md_norm)
    if start is None:
        return None
    # End: the section's closing words, searched from 60% of its length on; they can sit
    # in a table laid out differently, so earlier closing windows are tried too. Failing
    # that, the end is estimated from the section's length.
    # Boilerplate closing sentences can repeat in a filing, so of every occurrence of the
    # closing words, the one ending closest to the expected end (start + length) wins.
    length = len(sec_norm)
    expected = start + length
    window = min(ANCHOR, length)
    end_norm = None
    for back in range(0, length // 10 + 1, max(1, length // 50)):
        stop = length - back
        tail = sec_norm[max(0, stop - window) : stop]
        ends = []
        at = md_norm.find(tail, start + int(0.5 * stop) - window)
        while 0 <= at < start + 2 * length:
            ends.append(at + len(tail) + back)
            at = md_norm.find(tail, at + 1)
        if ends:
            end_norm = min(ends, key=lambda e: abs(e - expected))
            break
    if end_norm is None:
        end_norm = expected
    end_norm = min(end_norm, len(md_index))
    return md_index[start], md_index[end_norm - 1] + 1


def whole_lines(markdown: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span to whole lines, so a section keeps its heading's start and its last
    line's closing punctuation (e.g. the ")" of "(1,577)")."""
    line_start = markdown.rfind("\n", 0, start) + 1
    line_end = markdown.find("\n", end)
    return line_start, len(markdown) if line_end < 0 else line_end


def _item_of(line: str) -> str | None:
    m = _HEADING.match(line)
    return m.group("item").upper() if m else None


def fit_to_headings(markdown: str, start: int, end: int, key: str) -> tuple[int, int]:
    """edgartools splits items a few words off: a section can end with the next item's
    heading line and miss its own "Item N." line just before it. Drop trailing item-heading
    lines, and take in the section's own heading if it is the line just above."""
    own_item = key.rsplit(" ", 1)[-1].upper()
    lines = markdown[start:end].rstrip().split("\n")
    while len(lines) > 1 and _item_of(lines[-1].strip()) not in (None, own_item):
        lines.pop()
        while len(lines) > 1 and not lines[-1].strip():
            lines.pop()
    end = start + len("\n".join(lines))

    # The nearest non-blank line above the section: is it this section's own heading?
    above = markdown[:start].rstrip().rsplit("\n", 1)
    above_line = above[-1]
    if _item_of(above_line.strip()) == own_item:
        start = len(markdown[:start].rstrip()) - len(above_line)
    return start, end


# --- Method 2: headings -----------------------------------------------------------------------

_HEADING = re.compile(
    r"^[#*| \t]*(?:part[ \t]+(?P<part>i{1,2})\W*)?item[ \t ]*(?P<item>\d{1,2}[a-c]?)"
    r"[ \t]*\\?[.:\-—*]",  # "Item 7." or, escaped as edgartools writes it, "Item 7\."
    re.IGNORECASE | re.MULTILINE,
)


def _section_key(form: str, part: str | None, item: str) -> str:
    item = item.upper()
    if form == "10-K":
        return f"Item {item}"
    return f"Part {(part or '').upper()}, Item {item}" if part else f"Item {item}"


def headings(markdown: str, form: str) -> list[tuple[int, str]]:
    """(offset, key) for lines that start with an item heading, outside tables. For 10-Qs,
    headings without an explicit part are assigned Part I until a Part II heading or an
    item number repeats."""
    found = []
    part = "I"
    seen: set[str] = set()
    for m in _HEADING.finditer(markdown):
        line_end = markdown.find("\n", m.start())
        line = markdown[m.start() : line_end if line_end >= 0 else len(markdown)].strip()
        # Table rows are skipped (tables of contents, cross-references), except a one-cell
        # table holding just the heading, as some filers write it: "| Item 7. ... |"
        if line.startswith("|") and line.count("|") != 2:
            continue
        item = m.group("item").upper()
        if form == "10-Q":
            if m.group("part"):
                part = m.group("part").upper()
            elif item in seen and part == "I":
                part = "II"
            key = f"Part {part}, Item {item}"
            seen.add(item)
        else:
            key = f"Item {item}"
        found.append((m.start(), key))
    return found


def heading_span(markdown: str, form: str, key: str, after: int = 0) -> tuple[int, int] | None:
    """From the last heading for `key` (the first ones are usually the table of contents)
    to the next item heading after it."""
    hs = [h for h in headings(markdown, form) if h[0] >= after]
    starts = [i for i, (_, k) in enumerate(hs) if k == key]
    if not starts:
        return None
    # Prefer the occurrence followed by the most text before the next heading.
    best = None
    for i in starts:
        start = hs[i][0]
        end = hs[i + 1][0] if i + 1 < len(hs) else len(markdown)
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)
    return best


# --- Per filing -----------------------------------------------------------------------------


def parse_filing(markdown: str, edgar_sections: dict[str, str], form: str) -> list[Section]:
    md_norm, md_index = normalize(markdown)
    out: list[Section] = []
    for key in SECTIONS[form]:
        span, method = None, "edgartools"
        if key in edgar_sections:
            span = locate(edgar_sections[key], md_norm, md_index)
            # edgartools sometimes returns only the title (e.g. "ITEM 8. FINANCIAL
            # STATEMENTS..."); a much longer heading-based section is then the real one.
            if span is not None and len(normalize(edgar_sections[key])[0]) < 300:
                alt = heading_span(markdown, form, key)
                if alt and alt[1] - alt[0] > 3 * (span[1] - span[0]) + 2000:
                    span, method = alt, "heading"
        if span is None:
            span, method = heading_span(markdown, form, key), "heading"
        if span is None:
            continue
        if method == "edgartools":
            start, end = fit_to_headings(markdown, *whole_lines(markdown, *span), key)
        else:
            start, end = span
        out.append(Section(key, method, start, end, unescape(markdown[start:end]).strip()))
    return out


def run(manifest: list[dict[str, str]]) -> list[dict[str, Any]]:
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in manifest:
        markdown = (DATA_DIR.parent / row["markdown_path"]).read_text(encoding="utf-8")
        edgar = json.loads((DATA_DIR.parent / row["sections_path"]).read_text(encoding="utf-8"))
        sections = parse_filing(markdown, edgar, row["form"])
        out = SECTIONS_DIR / row["cik"] / f"{row['accession']}.json"
        save_atomic(out, json.dumps([asdict(s) for s in sections], ensure_ascii=False))
        s = stats[row["company"]]
        s["filings"] += 1
        s["expected"] += len(SECTIONS[row["form"]])
        got = {sec.section for sec in sections}
        for sec in sections:
            s[sec.method] += 1
        for key in SECTIONS[row["form"]]:
            if key not in got:
                s["failed" if key in edgar else "absent"] += 1
    rows = []
    for company in sorted(stats):
        s = stats[company]
        rows.append(
            {
                "company": company,
                "filings": s["filings"],
                "sections_expected": s["expected"],
                "edgartools": s["edgartools"],
                "heading_fallback": s["heading"],
                "absent": s["absent"],  # in neither edgartools nor a heading: not in filing
                "failed": s["failed"],  # edgartools had it but it could not be located
                "fallback_rate": round(s["heading"] / s["expected"], 3),
            }
        )
    return rows


def write_stats(rows: list[dict[str, Any]], path: Path = STATS_PATH) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rows = run(load_manifest(MANIFEST_PATH))
    write_stats(rows)
    total: Counter[str] = Counter()
    for r in rows:
        for k in ("sections_expected", "edgartools", "heading_fallback", "absent", "failed"):
            total[k] += int(r[k])
    print(f"{sum(int(r['filings']) for r in rows)} filings; sections: {dict(total)}")
    for r in rows:
        if float(r["fallback_rate"]) > 0.1 or int(r["failed"]):
            print(
                f"  look at {r['company']}: fallback {r['fallback_rate']}, "
                f"absent {r['absent']}, failed {r['failed']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
