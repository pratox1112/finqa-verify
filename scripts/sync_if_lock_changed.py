"""Run `uv sync` when a merge or checkout changed uv.lock (ROADMAP T1).

Called by the post-merge and post-checkout pre-commit hooks. Standard library only, so it
runs even when the project environment is missing or stale.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping

NULL_SHA = "0" * 40


def lock_changed(env: Mapping[str, str], diff: Callable[[str, str], str | None]) -> bool:
    """True if uv.lock differs between the refs this hook was called for.

    `diff(from_ref, to_ref)` returns the changed paths among uv.lock, or None if git failed.
    """
    if env.get("PRE_COMMIT_CHECKOUT_TYPE") == "0":  # checking out single files, not a branch
        return False
    from_ref = env.get("PRE_COMMIT_FROM_REF") or "ORIG_HEAD"  # post-merge has no refs
    to_ref = env.get("PRE_COMMIT_TO_REF") or "HEAD"
    if from_ref == NULL_SHA:  # fresh clone
        return True
    changed = diff(from_ref, to_ref)
    return changed is None or bool(changed.strip())  # sync if unsure


def _git_diff(from_ref: str, to_ref: str) -> str | None:
    result = subprocess.run(
        ["git", "diff", "--name-only", from_ref, to_ref, "--", "uv.lock"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout if result.returncode == 0 else None


def main() -> int:
    if not lock_changed(os.environ, _git_diff):
        return 0
    print("uv.lock changed: running uv sync")
    return subprocess.run(["uv", "sync"]).returncode


if __name__ == "__main__":
    sys.exit(main())
