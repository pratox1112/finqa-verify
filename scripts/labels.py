"""Human labelling sheets and agreement (finqa.eval.labels; docs/LABELING_PROTOCOL.md §3, §5, §6).

Judge-human agreement on text-gold answers:

    uv run python scripts/labels.py judge-sheets --name test-judge --runs <run_id> <run_id> ... \\
        --labellers alice bob carol --double 40
    # fill in runs/labels/test-judge/sheet_<name>.csv (correct: yes/no; note: optional)
    # (rows two labellers disagree on: runs/labels/test-judge/adjudication.csv, row_id,correct,note)
    uv run python scripts/labels.py judge-agreement --name test-judge

Gold errata, two annotators, blind to every system's answers:

    uv run python scripts/labels.py errata-sheets --name errata --annotators alice bob
    # fill in runs/labels/errata/errata_<name>.csv (verdict: matches/contradicts/unclear)
    uv run python scripts/labels.py errata-compare --name errata

Output goes to runs/labels/<name>/ (gitignored, like all run output); share the sheets through
the shared artifact location. Use first names or initials as labeller names: they appear in
file names and in annotations.jsonl. Never change a prompt or code because of what a test
sheet shows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from finqa.eval import labels
from finqa.eval.questions import load_questions
from finqa.eval.runner import RUNS_DIR, RunRefused
from finqa.eval.scoring import load_gold
from finqa.ingestion import financebench


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sheets = sub.add_parser("judge-sheets", help="blind sheets for judge-human agreement")
    sheets.add_argument("--name", required=True, help="folder under runs/labels/")
    sheets.add_argument("--runs", nargs="+", required=True, help="run IDs under runs/")
    sheets.add_argument("--labellers", nargs="+", required=True)
    sheets.add_argument("--double", type=int, default=0, help="rows given to two labellers")
    sheets.add_argument("--split", default="test", choices=["dev", "test"])
    sheets.add_argument("--seed", type=int, default=20261122)
    agree = sub.add_parser("judge-agreement", help="agreement from filled-in sheets")
    agree.add_argument("--name", required=True)
    errata = sub.add_parser("errata-sheets", help="one gold-errata sheet per annotator")
    errata.add_argument("--name", required=True)
    errata.add_argument("--annotators", nargs=2, required=True)
    compare = sub.add_parser("errata-compare", help="outcome per errata candidate")
    compare.add_argument("--name", required=True)
    return parser


def main(argv: list[str] | None = None, runs_dir: Path = RUNS_DIR) -> int:
    args = build_parser().parse_args(argv)
    out_dir = runs_dir / "labels" / args.name
    try:
        if args.command == "judge-sheets":
            questions = {q.question_id: q for q in load_questions(args.split)}
            items = labels.judged_items(runs_dir, args.runs, questions, load_gold())
            counts = labels.write_judge_sheets(
                items, args.labellers, args.double, out_dir, args.seed
            )
            print(f"{len(items)} answers -> {out_dir}")
            for name, n in counts.items():
                print(f"  sheet_{name}.csv: {n} rows")
        elif args.command == "judge-agreement":
            report, annotations = labels.judge_agreement(out_dir, runs_dir)
            print(f"-> {report}\n-> {annotations}")
        elif args.command == "errata-sheets":
            records = financebench.by_id(financebench.load())
            for path in labels.write_errata_sheets(records, args.annotators, out_dir):
                print(f"-> {path}")
        else:
            print(f"-> {labels.compare_errata(out_dir)}")
    except RunRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
