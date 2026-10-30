"""Fail a pull request that changes a frozen file without the `approved-freeze-change` label.

Frozen: src/finqa/schemas.py, data/splits.json, the `model:` section of configs/base.yaml,
the prompt manifest src/finqa/prompts/FROZEN.txt, and every prompt it lists.
Only files that already exist on the base branch are frozen; creating one is not a change.

Usage (CI): python scripts/check_frozen.py --base HEAD^1 --head HEAD [--approved]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Iterable
from typing import Any

import yaml

FROZEN_FILES = {"src/finqa/schemas.py", "data/splits.json"}
PROMPTS_DIR = "src/finqa/prompts/"
PROMPT_MANIFEST = PROMPTS_DIR + "FROZEN.txt"
BASE_CONFIG = "configs/base.yaml"

Reader = Callable[[str], str | None]  # path -> file text, or None if absent


def parse_manifest(text: str | None) -> set[str]:
    """Prompt paths listed in FROZEN.txt, one file name per line; `#` starts a comment."""
    if not text:
        return set()
    names = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return {PROMPTS_DIR + name for name in names if name}


def model_settings(text: str | None) -> Any:
    if not text:
        return None
    return (yaml.safe_load(text) or {}).get("model")


def find_violations(changed: Iterable[str], read_base: Reader, read_head: Reader) -> list[str]:
    changed = set(changed)
    frozen = FROZEN_FILES | {PROMPT_MANIFEST} | parse_manifest(read_base(PROMPT_MANIFEST))
    violations = [
        f"{path} is frozen" for path in sorted(changed & frozen) if read_base(path) is not None
    ]
    if BASE_CONFIG in changed:
        base_text = read_base(BASE_CONFIG)
        if base_text is not None and model_settings(base_text) != model_settings(
            read_head(BASE_CONFIG)
        ):
            violations.append(f"{BASE_CONFIG}: model settings are frozen")
    return violations


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")


def _reader(rev: str) -> Reader:
    def read(path: str) -> str | None:
        result = _git("show", f"{rev}:{path}")
        return result.stdout if result.returncode == 0 else None

    return read


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="revision the PR is compared against")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--approved", action="store_true", help="PR has approved-freeze-change")
    args = parser.parse_args()

    diff = _git("diff", "--name-only", "--no-renames", args.base, args.head)
    if diff.returncode != 0:
        print(diff.stderr, file=sys.stderr)
        return 2
    violations = find_violations(diff.stdout.splitlines(), _reader(args.base), _reader(args.head))

    if not violations:
        print("No frozen files changed.")
        return 0
    for v in violations:
        print(f"  - {v}")
    if args.approved:
        print("Frozen files changed, allowed by the approved-freeze-change label.")
        return 0
    print(
        "Frozen files changed. Get team approval, then add the label approved-freeze-change "
        "to this PR (see CONTRIBUTING.md)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
