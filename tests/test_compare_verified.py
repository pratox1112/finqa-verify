"""scripts/compare_verified.py: V0 vs V1 vs V2 flips on a dev run (tables only, no model)."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from finqa.eval.runner import RunRefused
from finqa.eval.tables import Row
from finqa.schemas import Claim, VerifiedResult

ROOT = Path(__file__).resolve().parents[1]


def load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "compare_verified", ROOT / "scripts" / "compare_verified.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(qid: str, outcome: str) -> Row:
    return Row(qid, "calculation", outcome, "number", "", 1.0, 1, 1, False)


def verified(
    qid: str, changed: bool, flagged: list[str], error: str | None = None
) -> VerifiedResult:
    claim = Claim(claim_id="c1", metric="m", value=1.0, unit="USD", period="FY2022", chunk_ids=[])
    after = claim.model_copy(update={"value": 2.0}) if changed else claim
    return VerifiedResult(
        question_id=qid,
        retrieval_arm="rag",
        verification_arm="grounded",
        claims_before=[claim],
        claims_after=[after],
        verdicts=[],
        revisions_used=int(changed),
        flagged_claim_ids=flagged,
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
        error=error,
    )


def test_summary_counts_flips_revisions_flags_and_failures() -> None:
    script = load()
    v0 = [row("q1", "correct"), row("q2", "incorrect"), row("q3", "incorrect")]
    v2 = [row("q1", "incorrect"), row("q2", "correct"), row("q3", "incorrect")]
    results = [verified("q1", True, []), verified("q2", True, []), verified("q3", False, ["c1"])]
    lines = script.summary_rows(v0, {"V2": (v2, results)})
    assert lines[2] == "| V0 | 1/3 | | | | | |"
    assert lines[3] == "| V2 | 1/3 | 1 | 1 | 2 | 1 | 0 |"
    table = script.per_question(v0, {"V2": (v2, results)})
    assert table[2] == "| `q1` | correct | incorrect | 1, none |"
    assert table[4] == "| `q3` | incorrect | incorrect | 0, c1 |"
    failed = [verified("q1", False, [], error="ValueError: no call")]
    assert "error: ValueError: no call" in script.per_question(v0[:1], {"V1": (v0[:1], failed)})[2]


def test_refuses_test_runs(tmp_path: Path) -> None:
    run = tmp_path / "r"
    run.mkdir()
    (run / "run_meta.json").write_text('{"split": "test"}', encoding="utf-8")
    with pytest.raises(RunRefused, match="dev only"):
        load().compare_verified("r", runs_dir=tmp_path)
