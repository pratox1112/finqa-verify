"""Guard the Claude Code permission rules that enforce ROADMAP T17."""

import json
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"
TOOLS = ["Bash", "PowerShell"]
# The state-changing commands T17 names explicitly.
T17_DENIED = [
    "git add",
    "git commit",
    "git checkout",
    "git switch",
    "git merge",
    "git rebase",
    "git reset",
    "git stash",
    "git tag",
    "git pull",
    "git fetch",
    "git push",
    "git branch -d",
    "git branch -D",
    "gh",
]
READ_ONLY = ["git status", "git diff", "git log", "git show"]


@pytest.fixture(scope="module")
def permissions() -> dict[str, list[str]]:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("command", T17_DENIED)
def test_state_changing_commands_denied(permissions, tool: str, command: str) -> None:
    assert f"{tool}({command} *)" in permissions["deny"]


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("command", READ_ONLY)
def test_read_only_commands_allowed(permissions, tool: str, command: str) -> None:
    assert f"{tool}({command} *)" in permissions["allow"]


def test_no_blanket_git_deny(permissions) -> None:
    # Deny beats allow, so a blanket rule would also block the read-only commands.
    assert not {"Bash(git *)", "PowerShell(git *)", "Bash(git:*)"} & set(permissions["deny"])


def test_github_api_denied(permissions) -> None:
    assert "WebFetch(domain:api.github.com)" in permissions["deny"]
