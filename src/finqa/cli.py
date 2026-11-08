"""`finqa` command line (ROADMAP P2.2).

uv run finqa draft  --config configs/grid/r0_v0.yaml --split dev
uv run finqa draft  --config configs/grid/r0_v0.yaml --split test --subset data/midterm_subset.json
uv run finqa verify --run <run_id> --config configs/grid/r0_v1.yaml
uv run finqa report --milestone m1
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finqa", description="finqa-verify experiment runs")
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft", help="run a generator over a split and save its drafts")
    draft.add_argument("--config", required=True, help="experiment YAML under configs/")
    draft.add_argument(
        "--split", choices=["dev", "test"], default=None, help="default: data.question_split"
    )
    draft.add_argument("--limit", type=int, default=None, help="first N questions (dev only)")
    draft.add_argument(
        "--subset", type=Path, default=None, help="only the IDs in this file (frozen subsets)"
    )

    verify = sub.add_parser("verify", help="run a verifier over a run's saved drafts")
    verify.add_argument("--run", required=True, help="run ID under runs/")
    verify.add_argument("--config", required=True, help="experiment YAML under configs/")

    report = sub.add_parser("report", help="regenerate a milestone's tables and figures")
    report.add_argument("--milestone", required=True, choices=["m1"])
    report.add_argument(
        "--scope",
        choices=["full", "subset"],
        default="full",
        help="full test split (default) or the frozen midterm subset",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from finqa.eval import runner

    args = build_parser().parse_args(argv)
    try:
        if args.command == "draft":
            return runner.draft_command(
                args.config, split=args.split, limit=args.limit, subset=args.subset
            )
        if args.command == "report":
            from finqa.eval import report

            return report.report_command(args.milestone, args.scope)
        return runner.verify_command(args.run, args.config)
    except runner.RunRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except runner.RunStopped as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
