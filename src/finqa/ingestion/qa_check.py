"""Automated quality checks (ROADMAP P1.9, replacing the manual review: DECISIONS.md
2026-11-01): every parsed 10-K, checked three ways.

  1. Tables and unit scale: four line items in Item 8 (total assets, revenue, net income,
     operating cash flow), each value times its table's detected unit scale, must equal the
     company's own XBRL value for that fiscal year. A value that only matches at another
     scale means the scale is missing or wrong; no matching value means a broken table
     (or a row label this check does not know: reported, not passed).
  2. Sections: each kept section opens with its item's title.
  3. Text: no garbled characters (U+FFFD, mojibake such as "â€™").

XBRL is used here only to check our own parsing, never to score answers.

    uv run python -m finqa.ingestion.qa_check
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finqa.ingestion.chunk import CHUNKS_DIR, _cells
from finqa.ingestion.download import MANIFEST_PATH, load_manifest
from finqa.ingestion.financebench import DATA_DIR
from finqa.ingestion.parse import SECTIONS_DIR, titled
from finqa.ingestion.review import question_counts
from finqa.ingestion.xbrl import FACTS_DIR, Metric, load_metric_map, lookup_metric
from finqa.schemas import Chunk

CHECKS_PATH = DATA_DIR / "QA_CHECKS.md"
METRICS = ("total_assets", "revenue", "net_income", "operating_cash_flow")
SCALES = (1.0, 1e3, 1e6, 1e9)
MIN_DIGITS_VALUE = 100  # a number needs 3 significant digits to count as a scale mismatch
# U+FFFD, UTF-8 read as Latin-1 ("â€™"), and Windows-1252 punctuation left as control
# characters ("\x92" for an apostrophe, "\x97" for a dash)
GARBLED = re.compile(r"�|â€|Ã[\x80-\xbf]|[\x80-\x9f]")

# Where a metric's XBRL value turned up, best first.
PASS = "pass"  # an Item 8 table row with a label, at the table's detected scale
NO_LABEL = "no label"  # only in Item 8 rows whose label cell is empty
ELSEWHERE = "outside Item 8"  # only in tables of another section
SCALE = "scale"  # only at a scale other than the detected one
MISSING = "missing"  # in no table at any scale
NO_XBRL = "no XBRL"  # the company reported no value: not checked
FAILURES = (NO_LABEL, ELSEWHERE, SCALE, MISSING)


# --- Tables and unit scale --------------------------------------------------------------------


def numbers(row: str) -> list[tuple[float, int]]:
    """The numeric cells of a table row (not its label), as (absolute value, decimals)."""
    out = []
    for cell in _cells(row)[1:]:
        m = re.fullmatch(r"[($]*\s*(\d{1,3}(?:,\d{3})*|\d+)(\.\d+)?\s*\)?%?", cell)
        if m:
            decimals = len(m.group(2)) - 1 if m.group(2) else 0
            out.append((float(m.group(1).replace(",", "") + (m.group(2) or "")), decimals))
    return out


def matches(shown: float, decimals: int, scale: float, targets: list[float]) -> bool:
    """Does the shown number, at this scale, equal a target up to its rounding?"""
    tolerance = 0.5 * scale * 10.0**-decimals + 0.5
    return any(abs(shown * scale - abs(t)) <= tolerance for t in targets)


@dataclass
class Result:
    metric: str
    status: str
    detail: str = ""


def check_metric(metric: str, chunks: list[Chunk], targets: list[float]) -> Result:
    """Look for the XBRL value in every table row of the filing; report the best place."""
    if not targets:
        return Result(metric, NO_XBRL)
    found: dict[str, str] = {}
    for c in chunks:
        if not c.is_table:
            continue
        for row in c.text.split("\n"):
            if not row.startswith("|"):
                continue
            for shown, decimals in numbers(row):
                if matches(shown, decimals, c.unit_scale or 1.0, targets):
                    if c.section != "Item 8":
                        found.setdefault(ELSEWHERE, f"`{c.chunk_id}`")
                    elif _cells(row)[0]:
                        return Result(metric, PASS)
                    else:
                        found.setdefault(NO_LABEL, f"`{c.chunk_id}`")
                elif (
                    c.section == "Item 8"
                    and shown * 10**decimals >= MIN_DIGITS_VALUE  # "4" fits anything in billions
                    and any(matches(shown, decimals, s, targets) for s in SCALES)
                ):
                    found.setdefault(
                        SCALE, f"`{c.chunk_id}` detected {c.unit_scale}: {shown:,g} doesn't fit"
                    )
    for status in (NO_LABEL, ELSEWHERE, SCALE):
        if status in found:
            return Result(metric, status, found[status])
    return Result(metric, MISSING, f"XBRL {targets[0]:,.0f} in no table")


def xbrl_targets(
    cik: str, period: str, metric_map: dict[str, Metric], manifest: list[dict[str, str]]
) -> dict[str, list[float]]:
    return {
        m: [f.value for f in lookup_metric(cik, m, period, metric_map, manifest, FACTS_DIR)]
        for m in METRICS
    }


# --- Sections and text ------------------------------------------------------------------------


def check_sections(sections: list[dict[str, Any]]) -> list[str]:
    """Kept sections that don't open with their item's title, with their first words."""
    return [
        f'{s["section"]} starts "{" ".join(s["text"].split())[:60]}…"'
        for s in sections
        if s["text"] and not titled(s["text"], s["section"])
    ]


def garbled(chunks: list[Chunk]) -> int:
    return sum(len(GARBLED.findall(c.text)) for c in chunks)


# --- Run --------------------------------------------------------------------------------------


def load_chunks(cik: str, accession: str, root: Path = CHUNKS_DIR) -> list[Chunk]:
    path = root / cik / f"{accession}.jsonl"
    return [Chunk(**json.loads(x)) for x in path.read_text(encoding="utf-8").split("\n") if x]


def check_filing(
    row: dict[str, str], metric_map: dict[str, Metric], manifest: list[dict[str, str]]
) -> dict[str, Any]:
    chunks = load_chunks(row["cik"], row["accession"])
    sections = json.loads(
        (SECTIONS_DIR / row["cik"] / f"{row['accession']}.json").read_text(encoding="utf-8")
    )
    targets = xbrl_targets(row["cik"], row["period"], metric_map, manifest)
    return {
        "row": row,
        "tables": [check_metric(m, chunks, targets[m]) for m in METRICS],
        "untitled": check_sections(sections),
        "garbled": garbled(chunks),
    }


def verdict(result: dict[str, Any]) -> str:
    """flag: a line item not found as it should be, or garbled text; warn: a total row
    without a label, or a section that doesn't open with its title; else pass."""
    statuses = {t.status for t in result["tables"]}
    if statuses & {ELSEWHERE, SCALE, MISSING} or result["garbled"]:
        return "flag"
    if NO_LABEL in statuses or result["untitled"]:
        return "warn"
    return "pass"


def problems(result: dict[str, Any]) -> list[str]:
    out = [f"{t.metric}: {t.status} ({t.detail})" for t in result["tables"] if t.status in FAILURES]
    out += [f"section {u}" for u in result["untitled"]]
    if result["garbled"]:
        out.append(f"{result['garbled']} garbled characters")
    return out


HEADER = """# Quality checks (ROADMAP P1.9)

Automated checks on every parsed 10-K, replacing the manual review (docs/DECISIONS.md,
2026-11-01, "Automated quality checks"). Generated by `uv run python -m
finqa.ingestion.qa_check`; don't edit by hand. What each flag means, and which are known
limitations, is in DECISIONS.md.

- **Line items:** total assets, revenue, net income and operating cash flow must appear in an
  Item 8 table row, at the table's detected unit scale, equal to the company's own XBRL value
  for that year. `no label`: found only in a row with an empty label; `outside Item 8`: only
  in another section; `scale`: only at a different scale; `missing`: in no table.
  `no XBRL`: not checked.
- **Sections:** each kept section opens with its item's title.
- **Text:** no garbled characters (U+FFFD, mojibake, Windows-1252 control characters).
"""


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render(results: list[dict[str, Any]], questions: Counter[tuple[str, int]]) -> str:
    def qs(r: dict[str, str]) -> int:
        return questions.get((r["company"], int(r["fiscal_year"])), 0)

    verdicts = Counter(verdict(r) for r in results)
    items = Counter(t.status for r in results for t in r["tables"])
    out = [
        HEADER,
        f"**{len(results)} 10-Ks:** {verdicts['pass']} pass, {verdicts['warn']} warn, "
        f"{verdicts['flag']} flag. **Line items:** "
        + ", ".join(f"{n} {s}" for s, n in items.most_common())
        + ".",
        "",
        "## Flagged and warned filings",
        "",
        "| Company | 10-K | FinanceBench questions | Verdict | Problems |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if verdict(r) != "pass":
            row = r["row"]
            out.append(
                f"| {row['company']} | {row['period']} | {qs(row)} | {verdict(r)} | "
                + _cell("; ".join(problems(r)))
                + " |"
            )
    names = " | ".join(m.replace("_", " ") for m in METRICS)
    out += [
        "",
        "## All 10-Ks",
        "",
        f"| Company | 10-K | Questions | {names} | Sections | Garbled | Verdict |",
        "|---|---|---|" + "---|" * len(METRICS) + "---|---|---|",
    ]
    for r in results:
        row = r["row"]
        cells = [t.status for t in r["tables"]]
        sections = f"{len(r['untitled'])} untitled" if r["untitled"] else "ok"
        out.append(
            f"| {row['company']} | {row['period']} | {qs(row)} | "
            + " | ".join(cells)
            + f" | {sections} | {r['garbled']} | {verdict(r)} |"
        )
    return "\n".join(out) + "\n"


def main() -> int:
    manifest = load_manifest(MANIFEST_PATH)
    metric_map = load_metric_map()
    results = [check_filing(r, metric_map, manifest) for r in manifest if r["form"] == "10-K"]
    CHECKS_PATH.write_text(render(results, question_counts()), encoding="utf-8")
    for r in results:
        if verdict(r) == "flag":
            print(f"flag {r['row']['company']} {r['row']['period']}: {'; '.join(problems(r))}")
    print(Counter(verdict(r) for r in results), f"-> {CHECKS_PATH.relative_to(DATA_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
