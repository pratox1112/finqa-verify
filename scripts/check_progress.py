"""Validate PROGRESS.md against ROADMAP.md (ROADMAP P0.10, T5).

Checks:
  - every task and gate ID in ROADMAP.md appears exactly once in PROGRESS.md, and no others do;
  - every status is one of todo, in-progress, review, blocked, done;
  - every `done` row links a pull request;
  - every `blocked` row has an entry in the Blockers table.
With --base (CI, pull requests), also fails if the PR did not change PROGRESS.md,
unless --exempt (the PR has the `no-progress-update` label).

Standard library only, so CI can run it without installing the project.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

STATUSES = {"todo", "in-progress", "review", "blocked", "done"}
TASK_RE = re.compile(r"^\s*- \*\*([PM]\d+\.\d+)\b", re.MULTILINE)
GATE_RE = re.compile(r"^\s*- \*\*GATE (\w+)", re.MULTILINE)
ID_RE = re.compile(r"^(?:[PM]\d+\.\d+|G\w+)$")
PR_LINK_RE = re.compile(r"/pull/\d+")


def roadmap_ids(roadmap: str) -> list[str]:
    """Task IDs (P1.6, M1.3) and gate IDs (GATE 0 -> G0, GATE M1 -> GM1), in order."""
    return TASK_RE.findall(roadmap) + ["G" + g for g in GATE_RE.findall(roadmap)]


def _sections(text: str) -> dict[str, list[list[str]]]:
    """Table rows (as stripped cells) grouped by their `## ` section heading."""
    sections: dict[str, list[list[str]]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        elif line.startswith("|"):
            cells = [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]
            sections.setdefault(current, []).append(cells)
    return sections


def check_progress(progress: str, roadmap: str) -> list[str]:
    errors: list[str] = []
    sections = _sections(progress)
    blockers = {row[0] for row in sections.pop("Blockers", []) if row and ID_RE.match(row[0])}
    rows = [row for rows in sections.values() for row in rows if row and ID_RE.match(row[0])]

    expected = roadmap_ids(roadmap)
    seen: dict[str, int] = {}
    for row in rows:
        seen[row[0]] = seen.get(row[0], 0) + 1
    for task_id in expected:
        if task_id not in seen:
            errors.append(f"{task_id}: in ROADMAP.md but missing from PROGRESS.md")
    for task_id, count in seen.items():
        if count > 1:
            errors.append(f"{task_id}: appears {count} times")
        if task_id not in expected:
            errors.append(f"{task_id}: not a task or gate in ROADMAP.md")

    for row in rows:
        task_id = row[0]
        if len(row) < 5:
            errors.append(f"{task_id}: row has {len(row)} columns, expected 7")
            continue
        status, branch_pr = row[2], row[4]
        if status not in STATUSES:
            errors.append(
                f"{task_id}: invalid status {status!r} (use {', '.join(sorted(STATUSES))})"
            )
        if status == "done" and not PR_LINK_RE.search(branch_pr):
            errors.append(f"{task_id}: done but Branch / PR has no pull request link")
        if status == "blocked" and task_id not in blockers:
            errors.append(f"{task_id}: blocked but has no entry under Blockers")
    return errors


def progress_changed(base: str, head: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head, "--", "PROGRESS.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return bool(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PROGRESS.md against ROADMAP.md.")
    parser.add_argument("--progress", type=Path, default=Path("PROGRESS.md"))
    parser.add_argument("--roadmap", type=Path, default=Path("ROADMAP.md"))
    parser.add_argument("--base", help="PR base revision; require PROGRESS.md to change")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--exempt", action="store_true", help="PR has no-progress-update")
    args = parser.parse_args()

    errors = check_progress(
        args.progress.read_text(encoding="utf-8"), args.roadmap.read_text(encoding="utf-8")
    )
    if args.base and not args.exempt and not progress_changed(args.base, args.head):
        errors.append(
            "PROGRESS.md was not updated in this PR. Update your task's row and add a Log line, "
            "or add the no-progress-update label if this PR has no task (ROADMAP T5)."
        )

    if errors:
        print("PROGRESS.md check failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PROGRESS.md is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
