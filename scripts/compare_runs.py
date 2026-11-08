"""Per-question agreement between two dev runs (Groq vs self-hosted serving).

    uv run python scripts/compare_runs.py --a <run_id> --b <run_id>

See finqa.eval.compare.
"""

from __future__ import annotations

import argparse
import sys

from finqa.eval.compare import compare_command
from finqa.eval.runner import RunRefused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True, help="reference run ID under runs/ (e.g. Groq)")
    parser.add_argument("--b", required=True, help="compared run ID under runs/ (e.g. vLLM)")
    args = parser.parse_args()
    try:
        return compare_command(args.a, args.b)
    except RunRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
