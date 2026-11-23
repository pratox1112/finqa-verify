"""V0: no verification, the control condition (ROADMAP P4.1, guide §4.1).

Returns the draft's claims unchanged: no checks, no revisions, no model calls. Scoring V0
results gives the same outcomes as scoring the drafts directly.
"""

from __future__ import annotations

from finqa.config import Config
from finqa.schemas import Draft, VerifiedResult
from finqa.verifiers.base import result


def verify(draft: Draft, cfg: Config) -> VerifiedResult:
    """The runner's entry point for the "none" arm (finqa.eval.runner.VERIFIERS)."""
    return result(draft, cfg)
