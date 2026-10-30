"""Shared number reader: text -> (value, unit). Used by gold extraction (P1.2), scoring
(P2.3) and grounded verification (P4.3), so all three read numbers the same way.

Conventions (docs/DECISIONS.md): values in full units, never pre-scaled ("$1.2B" is
1200000000); percentages as the percent number ("12.5%" is 12.5); negatives from a minus
sign or accounting parentheses ("(1,234)" is -1234). Units are the shared schema `Unit`s;
`None` means the text alone doesn't say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from finqa.schemas import Unit

SCALES = {
    "thousand": 1e3,
    "thousands": 1e3,
    "k": 1e3,
    "million": 1e6,
    "millions": 1e6,
    "mn": 1e6,
    "mm": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "billions": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
    "trillions": 1e12,
}

_NUMBER = re.compile(
    r"""
    (?<![\w.])                                   # not inside a word, code or another number
    (?P<sign>[-−])?\s*
    (?P<open>\()?\s*
    (?P<sign2>[-−])?\s*
    (?P<cur>\$|USD\s*|US\$\s*)?\s*
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    (?:
        (?P<abbr>k|mn|mm|m|bn|b)(?![a-z])        # "$1.2B", "$450M": abbreviation right after
      | \s*(?P<word>thousands?|millions?|billions?|trillions?)\b
    )?
    \s*(?P<close>\))?
    \s*(?P<pct>%|percent(?:age)?(?:\s*points?)?\b)?
    \s*(?P<tail>per\s+(?:diluted\s+|basic\s+)?share|/\s*share|shares\b|days\b|x\b|times\b)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    unit: Unit | None
    text: str  # the matched span


def _to_parsed(m: re.Match[str]) -> ParsedNumber | None:
    raw = m.group("num").replace(",", "")
    value = float(raw)
    has_context = any(m.group(g) for g in ("cur", "abbr", "word", "pct", "tail"))
    if not has_context and "." not in raw and 1900 <= value <= 2100:
        return None  # a bare four-digit year, e.g. "FY 2022"
    scale_text = (m.group("abbr") or m.group("word") or "").lower()
    value *= SCALES.get(scale_text, 1.0)
    negative = bool(m.group("sign") or m.group("sign2")) or bool(
        m.group("open") and m.group("close")
    )
    if negative:
        value = -value

    tail = (m.group("tail") or "").lower()
    unit: Unit | None
    if "share" in tail and tail != "shares":
        unit = "USD/share"
    elif m.group("pct"):
        unit = "%"
    elif tail == "shares":
        unit = "shares"
    elif tail == "days":
        unit = "days"
    elif tail in ("x", "times"):
        unit = "ratio"
    elif m.group("cur"):
        unit = "USD"
    else:
        unit = None
    return ParsedNumber(value=value, unit=unit, text=m.group(0).strip())


def extract_numbers(text: str) -> list[ParsedNumber]:
    """Every number in `text`, in order (bare years are skipped)."""
    found = (_to_parsed(m) for m in _NUMBER.finditer(text))
    return [p for p in found if p is not None]


def parse_number(text: str) -> ParsedNumber | None:
    """The number if `text` is exactly one number (e.g. "$1,577.00", "(12.5%)"), else None."""
    stripped = text.strip().rstrip(".")
    m = _NUMBER.fullmatch(stripped)
    return _to_parsed(m) if m else None


# --- Units stated in a question --------------------------------------------------------

_Q_SCALE = re.compile(
    r"\b(?:in\s+)?(?:usd|us\$|\$|dollars)\s*(thousands?|millions?|billions?)\b"
    r"|\bin\s+(thousands|millions|billions)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuestionUnit:
    unit: Unit | None
    scale: float = 1.0


def question_unit(question: str) -> QuestionUnit:
    """The unit a question asks for, used when the gold answer is a bare number.

    "(in USD millions)" -> USD x 1e6; "in units of percents" / "% margin" -> %;
    "per share" -> USD/share; "days", "cash conversion cycle", DSO/DIO/DPO -> days;
    "ratio", "turnover", "times", return on assets/equity -> ratio.
    """
    q = question.lower()
    if re.search(r"per\s+(?:diluted\s+|basic\s+)?share|\beps\b", q):
        return QuestionUnit("USD/share")
    if re.search(r"percent|%|\bmargin\b|growth rate", q):
        return QuestionUnit("%")
    scale = _Q_SCALE.search(q)
    if scale:
        word = (scale.group(1) or scale.group(2)).lower()
        return QuestionUnit("USD", SCALES[word])
    if re.search(r"\bdays\b|cash conversion cycle|\b(?:ccc|dso|dio|dpo)\b", q):
        return QuestionUnit("days")
    if re.search(r"\bratio\b|turnover|\btimes\b|return on (?:assets|equity)|\b(?:roa|roe)\b", q):
        return QuestionUnit("ratio")
    return QuestionUnit(None)


def gold_value(question: str, answer: str) -> ParsedNumber | None:
    """The gold value of a single-number answer, with the question's stated unit applied.

    "$1577.00" for a question asking "in USD millions" -> 1577000000 USD (docs/DECISIONS.md).
    Returns None for answers that are not a single number (sentences are scored per claim).
    """
    parsed = parse_number(answer)
    if parsed is None:
        return None
    hint = question_unit(question)
    has_own_scale = bool(re.search(r"[a-z]", parsed.text.replace("USD", ""), re.IGNORECASE))
    unit = parsed.unit
    value = parsed.value
    if hint.unit == "USD/share" and unit in (None, "USD"):
        unit = "USD/share"
    elif unit is None:
        unit = hint.unit
        if unit == "USD" and not has_own_scale:
            value *= hint.scale
    elif unit == "USD" and hint.unit == "USD" and not has_own_scale:
        value *= hint.scale
    return ParsedNumber(value=value, unit=unit, text=parsed.text)
