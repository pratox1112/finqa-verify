"""Section parsing (ROADMAP P1.5): each filing's kept sections as clean Markdown.

edgartools splits filings into items reliably but returns them as plain text, which
flattens tables. So each section is cut from the filing's Markdown (tables intact):

  1. "edgartools": the edgartools section's opening and closing words are located in the
     Markdown (comparing letters and digits only, so formatting doesn't matter);
  2. "heading" (fallback, logged): where edgartools has no section or its words can't be
     found, or its section doesn't open with the item's title while the filing's own
     heading does (edgartools took note "7. Income Taxes" for Corning's Item 7), the
     section runs from its own heading ("Item 7." at the start of a line, not in a table)
     to the next item heading.
  3. 10-K Item 8 with no financial statements ("See Item 15"): the statements are added
     from wherever the filer printed them, "statements" (later in the filing, or inside
     another kept section) or "exhibit13" (Exhibit 13, downloaded with the filing).

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
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from finqa.ingestion.download import MANIFEST_PATH, SECTIONS, exhibit13_path, load_manifest
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

# At a line start, or right after a page footer's "Index" link on the same line (Corning
# FY2019-20: "...All Rights Reserved. <u>Index</u> # Item 7. Management's Discussion").
_HEADING = re.compile(
    r"(?:^|(?<=<u>Index</u> ))"
    r"[#*| \t]*(?:part[ \t]+(?P<part>i{1,2})\W*)?item[ \t ]*(?P<item>\d{1,2}[a-c]?)"
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


# --- Financial statements outside Item 8 (10-K) -----------------------------------------------
# About one 10-K in six says only "see Item 15" (or "see page F-1") in Item 8 and prints the
# statements elsewhere: after Item 15 or the signatures (Activision, Netflix, PayPal, Ulta,
# Corning), inside the span edgartools calls Item 7 (PepsiCo), or in Exhibit 13 (CVS, Pfizer,
# Verizon, Walmart in some years). Those statements are added to Item 8.

# An auditor's report title anywhere on a line (CVS writes "February 14, 2018 **Report of
# Independent...**"), or a statement title alone on a line or in a table row's first cell
# (Verizon, Corning: "| Consolidated Balance Sheets | Corning Incorporated... |"). "...Data"
# summaries and table-of-contents rows (with page numbers) are skipped in find_statements.
_STATEMENT_TITLE = re.compile(
    r"^[^\n]*\breport of independent registered public accounting firm\b[^\n]*$"
    r"|^[#*_| \t]*consolidated (?:statements?|balance sheets?)\b[^:\n]{0,200}$",
    re.IGNORECASE | re.MULTILINE,
)
# Table rows anywhere in the row; \s also matches the non-breaking spaces some filers use.
# Microsoft writes "Net cash used in investing", without "activities".
_BALANCE_SHEET = re.compile(r"^\|[^\n]*\btotal\s+assets\b", re.IGNORECASE | re.MULTILINE)
_CASH_FLOW = re.compile(r"^\|[^\n]*\binvesting\b", re.IGNORECASE | re.MULTILINE)
_SIGNATURES = re.compile(r"^[#*_ \t]*signatures?[*_ \t]*$", re.IGNORECASE | re.MULTILINE)
STATEMENT_WINDOW = 80_000  # the balance sheet and cash flows follow the first title within this


def has_statements(text: str) -> bool:
    """A balance sheet and a cash-flow statement: Markdown table rows mentioning "total
    assets" and "investing"."""
    return bool(_BALANCE_SHEET.search(text) and _CASH_FLOW.search(text))


def find_statements(markdown: str, start: int = 0, stop: int | None = None) -> int | None:
    """Offset of the first auditor's report or statement title (a line of its own, not
    "...Data" summaries) in [start, stop) followed by the statements."""
    for m in _STATEMENT_TITLE.finditer(markdown, start, len(markdown) if stop is None else stop):
        line = m.group(0)
        is_title = "registered public accounting firm" not in line.lower()
        if is_title and (
            "data" in line.lower() or (line.lstrip().startswith("|") and re.search(r"\d", line))
        ):
            continue
        if has_statements(markdown[m.start() : m.start() + STATEMENT_WINDOW]):
            return m.start()
    return None


def _first_outside(markdown: str, outside: Callable[[int], bool]) -> int | None:
    """The first statements start for which `outside(offset)` holds."""
    pos = 0
    while (s := find_statements(markdown, pos)) is not None:
        if outside(s):
            return s
        pos = s + 1
    return None


def _statements_end(markdown: str, form: str, start: int) -> int:
    """The next item heading or "Signatures" line after the statements begin."""
    ends = [o for o, _ in headings(markdown, form) if o > start]
    sig = _SIGNATURES.search(markdown, start + 1)
    if sig:
        ends.append(sig.start())
    return min(ends, default=len(markdown))


def complete_item8(
    markdown: str, sections: list[Section], exhibit13: str | None = None
) -> list[Section]:
    """A 10-K's sections with the financial statements in Item 8, wherever the filer put
    them. Tried in order: Item 8 cut at its own headings; statements after Item 8; statements
    anywhere outside the kept sections; Exhibit 13; statements inside another kept section
    (which then ends where they begin). Only when Item 8 has neither a balance-sheet nor a
    cash-flow row, so an Item 8 that has its statements is never changed."""
    by_key = {s.section: s for s in sections}
    item8 = by_key.get("Item 8")
    if item8 and (_BALANCE_SHEET.search(item8.text) or _CASH_FLOW.search(item8.text)):
        return sections
    new: Section | None = None
    host: Section | None = None

    def outside(s: int) -> bool:
        return not any(x.start <= s < x.end for x in sections)

    def statements_at(s: int) -> Section:
        end = _statements_end(markdown, "10-K", s)
        # keep the existing Item 8 text (e.g. "See Item 15") unless the span already holds it
        keep = item8 and not (s <= item8.start < end)
        lead = item8.text + "\n\n" if keep and item8 else ""
        return Section("Item 8", "statements", s, end, lead + unescape(markdown[s:end]).strip())

    alt = heading_span(markdown, "10-K", "Item 8")
    after = item8.end if item8 else 0
    s: int | None
    if alt and has_statements(markdown[alt[0] : alt[1]]):
        new = Section("Item 8", "heading", *alt, unescape(markdown[alt[0] : alt[1]]).strip())
    elif (s := find_statements(markdown, after)) is not None:
        new = statements_at(s)
    elif (s := _first_outside(markdown, outside)) is not None:
        new = statements_at(s)
    elif exhibit13 and (s := find_statements(exhibit13)) is not None:
        lead = item8.text + "\n\n" if item8 else ""
        new = Section("Item 8", "exhibit13", -1, -1, lead + unescape(exhibit13[s:]).strip())
    else:
        for other in sections:
            if other.section == "Item 8":
                continue
            s = find_statements(markdown, other.start, other.end)
            if s is not None:
                host = Section(
                    other.section,
                    other.method,
                    other.start,
                    s,
                    unescape(markdown[other.start : s]).strip(),
                )
                lead = item8.text + "\n\n" if item8 else ""
                text = lead + unescape(markdown[s : other.end]).strip()
                new = Section("Item 8", "statements", s, other.end, text)
                break
    if new is None:
        return sections
    out = [host if host and x.section == host.section else x for x in sections]
    return [x for x in out if x.section != "Item 8"] + [new]


# --- Per filing -----------------------------------------------------------------------------

# Each kept item's title, in letters and digits only, so formatting that splits words
# ("Busines s", "RIS **K FACTORS**") still matches.
_TITLES = {
    "Item 1": "business",
    "Item 1A": "riskfactors",
    "Item 7": "managementsdiscussion|mda",
    "Item 7A": "quantitative|marketrisk",
    "Item 8": "financialstatements|statementsof|balancesheet",
    "Part I, Item 1": "financialstatements|statementsof|balancesheet",
    "Part I, Item 2": "managementsdiscussion|mda",
    "Part I, Item 3": "quantitative|marketrisk",
    "Part I, Item 4": "controls",
    "Part II, Item 1A": "riskfactors",
}
TITLE_CHARS = 400  # the title must appear this close to the section's start


def titled(text: str, key: str) -> bool:
    """Does the section open with its item's title?"""
    return re.search(_TITLES[key], normalize(text[:TITLE_CHARS])[0]) is not None


MIN_HEADING_SECTION = 2000  # shorter heading spans are cross-references ("see pages 50-80")
TITLE_OPENING = 120  # characters of a heading span read for its title


def _better_heading(markdown: str, key: str, edgar: tuple[int, int], alt: tuple[int, int]) -> bool:
    """Replace an untitled edgartools section by the heading span only if that span is a
    real section (long enough, its first line carries the title) and edgartools' span lies
    mostly elsewhere in the filing."""
    if alt[1] - alt[0] < MIN_HEADING_SECTION:
        return False
    first_line = markdown[alt[0] : alt[1]].split("\n", 1)[0]
    # The title may run over a few lines: Corning FY2021 splits "Management’s" at the
    # apostrophe ("# Item 7. Management\n\n’\n\n**s Discussion...").
    opening = markdown[alt[0] : min(alt[1], alt[0] + TITLE_OPENING)]
    # "Item 1. Business–Government Regulation" (Pfizer) names a subsection, not the item
    if not titled(opening, key) or re.search("[–—]", first_line):
        return False
    overlap = max(0, min(edgar[1], alt[1]) - max(edgar[0], alt[0]))
    return overlap < 0.5 * (edgar[1] - edgar[0])


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
            # edgartools can mistake note numbers for items (Corning: "7. Income Taxes" as
            # Item 7). If its section doesn't open with the item's title but the filing's own
            # heading for the item does, the heading wins.
            if not titled(markdown[start:end], key):
                alt = heading_span(markdown, form, key)
                if alt and _better_heading(markdown, key, (start, end), alt):
                    (start, end), method = alt, "heading"
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
        if row["form"] == "10-K":
            ex13 = exhibit13_path(row["cik"], row["accession"])
            ex13_text = ex13.read_text(encoding="utf-8") if ex13.exists() else None
            sections = complete_item8(markdown, sections, ex13_text or None)
            item8 = next((x for x in sections if x.section == "Item 8"), None)
            if item8 is None or not has_statements(item8.text):
                stats[row["company"]]["no_statements"] += 1
                print(f"  no financial statements found: {row['company']} {row['period']}")
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
                # 10-K Item 8s completed with statements printed elsewhere / in Exhibit 13
                "item8_statements_added": s["statements"] + s["exhibit13"],
                "item8_no_statements": s["no_statements"],
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
