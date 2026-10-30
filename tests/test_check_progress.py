from pathlib import Path

from check_progress import check_progress, roadmap_ids

ROOT = Path(__file__).resolve().parents[1]

ROADMAP = """
- **P0.1 Repository skeleton**
- **P0.2 Configuration system**
- **GATE 0:** done.
- **M1.1 S0 on test** — run it.
- **GATE M1:** submitted.
"""

HEADER = (
    "| ID | Task | Status | Owner | Branch / PR | Updated | Notes |\n"
    "|---|---|---|---|---|---|---|\n"
)


def progress(rows: str, blockers: str = "") -> str:
    return (
        "## Blockers\n\n| Task | Waiting on | Who can unblock | Since |\n|---|---|---|---|\n"
        f"{blockers}\n## Phase 0\n\n{HEADER}{rows}"
    )


def row(task_id: str, status: str = "todo", pr: str = "") -> str:
    return f"| {task_id} | name | {status} | | {pr} | | |\n"


ALL_TODO = "".join(row(i) for i in ["P0.1", "P0.2", "G0", "M1.1", "GM1"])


def test_roadmap_ids_include_tasks_and_gates() -> None:
    assert roadmap_ids(ROADMAP) == ["P0.1", "P0.2", "M1.1", "G0", "GM1"]


def test_valid_progress_passes() -> None:
    assert check_progress(progress(ALL_TODO), ROADMAP) == []


def test_missing_task_fails() -> None:
    rows = ALL_TODO.replace(row("P0.2"), "")
    assert check_progress(progress(rows), ROADMAP) == [
        "P0.2: in ROADMAP.md but missing from PROGRESS.md"
    ]


def test_duplicate_and_unknown_ids_fail() -> None:
    errors = check_progress(progress(ALL_TODO + row("P0.1") + row("P9.9")), ROADMAP)
    assert "P0.1: appears 2 times" in errors
    assert "P9.9: not a task or gate in ROADMAP.md" in errors


def test_invalid_status_fails() -> None:
    rows = ALL_TODO.replace(row("P0.1"), row("P0.1", "finished"))
    assert len(check_progress(progress(rows), ROADMAP)) == 1


def test_done_needs_pr_link() -> None:
    rows = ALL_TODO.replace(row("P0.1"), row("P0.1", "done", "`some-branch`"))
    assert check_progress(progress(rows), ROADMAP) == [
        "P0.1: done but Branch / PR has no pull request link"
    ]
    linked = ALL_TODO.replace(row("P0.1"), row("P0.1", "done", "[#1](https://x/pull/1)"))
    assert check_progress(progress(linked), ROADMAP) == []


def test_blocked_needs_blocker_entry() -> None:
    rows = ALL_TODO.replace(row("P0.2"), row("P0.2", "blocked"))
    assert check_progress(progress(rows), ROADMAP) == [
        "P0.2: blocked but has no entry under Blockers"
    ]
    blocker = "| P0.2 | Groq model ID | Pratosh | 2026-10-30 |\n"
    assert check_progress(progress(rows, blocker), ROADMAP) == []


def test_real_progress_file_is_valid() -> None:
    errors = check_progress(
        (ROOT / "PROGRESS.md").read_text(encoding="utf-8"),
        (ROOT / "ROADMAP.md").read_text(encoding="utf-8"),
    )
    assert errors == []
