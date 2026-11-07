"""Build data/splits.json from the human-confirmed question types (ROADMAP P2.1).

Dev = the 20 model-pilot questions (data/pilot_questions.json), which are reserved for dev
because prompts were looked at during the pilot (docs/DECISIONS.md, 2026-10-30). Test = every
other in-scope question. Every row of data/question_types.csv must be confirmed first: the
script refuses to run while a `confirmed_type` is blank or not one of the four types.
Once on main, splits.json is frozen (CI frozen-file guard).

    uv run python scripts/make_splits.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES_CSV = ROOT / "data" / "question_types.csv"
PILOT = ROOT / "data" / "pilot_questions.json"
OUT = ROOT / "data" / "splits.json"
TYPES = ("single_fact", "multi_period", "calculation", "qualitative")


def build(rows: list[dict[str, str]], pilot_ids: set[str]) -> dict[str, object]:
    unconfirmed = [r["financebench_id"] for r in rows if r["confirmed_type"] not in TYPES]
    if unconfirmed:
        raise ValueError(f"{len(unconfirmed)} rows not confirmed, e.g. {unconfirmed[:3]}")
    missing = pilot_ids - {r["financebench_id"] for r in rows}
    if missing:
        raise ValueError(f"pilot questions not in scope: {sorted(missing)}")
    types = {r["financebench_id"]: r["confirmed_type"] for r in rows}
    dev = sorted(pilot_ids)
    test = sorted(set(types) - pilot_ids)
    return {
        "note": "Frozen once on main (ROADMAP P2.1). Dev = the 20 model-pilot questions.",
        "dev": dev,
        "test": test,
        "question_types": dict(sorted(types.items())),
        "counts": {
            split: dict(Counter(types[q] for q in ids))
            for split, ids in (("dev", dev), ("test", test))
        },
    }


def main() -> int:
    rows = list(csv.DictReader(TYPES_CSV.open(encoding="utf-8")))
    pilot_ids = {q["financebench_id"] for q in json.loads(PILOT.read_text("utf-8"))["questions"]}
    splits = build(rows, pilot_ids)
    OUT.write_text(json.dumps(splits, indent=2) + "\n", encoding="utf-8")
    print(f"dev {len(splits['dev'])} · test {len(splits['test'])} → {OUT.relative_to(ROOT)}")
    print(splits["counts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
