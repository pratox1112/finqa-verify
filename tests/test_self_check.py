"""V1 self-check (ROADMAP P4.2) with a fake chat model. No network."""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from test_agent import Recording
from test_generators import bad_request

from finqa.config import CONFIGS_DIR, Config, load_config
from finqa.generators.common import PROMPTS_DIR
from finqa.llm import LLM
from finqa.schemas import Chunk, Claim, Draft
from finqa.verifiers import self_check
from finqa.verifiers.self_check import SelfCheckVerifier, apply, cited_excerpts, format_claims

V1 = load_config(CONFIGS_DIR / "grid" / "r0_v1.yaml")
TABLE = Chunk(
    chunk_id="k1",
    cik="0000066740",
    ticker="MMM",
    form="10-K",
    fiscal_year=2018,
    period="FY2018",
    section="Item 8",
    is_table=True,
    unit_scale=1e6,
    text="| Purchases of PP&E | (1,577) | (1,373) |",
    source_accession="a1",
)


def claims(capex: float = 1_577_000_000.0, prior: float = 1_373_000_000.0) -> list[Claim]:
    return [
        Claim(
            claim_id="c1",
            metric="capex",
            value=capex,
            unit="USD",
            period="FY2018",
            chunk_ids=["k1"],
        ),
        Claim(
            claim_id="c2",
            metric="capex",
            value=prior,
            unit="USD",
            period="FY2017",
            chunk_ids=["k1"],
        ),
        Claim(
            claim_id="c3",
            metric="capex growth",
            value=14.86,
            unit="%",
            period="FY2018",
            chunk_ids=[],
            derived_from=["c1", "c2"],
            expression="(c1 - c2) / c2 * 100",
        ),
    ]


def draft(cs: list[Claim] | None = None, error: str | None = None) -> Draft:
    return Draft(
        question_id="q1",
        retrieval_arm="rag",
        answer_text="Capex grew 14.9% to $1,577M.",
        claims=claims() if cs is None else cs,
        answer_claim_id="c3",
        evidence={"k1": TABLE},
        trace_id="t",
        latency_s=1.0,
        tokens_in=1,
        tokens_out=1,
        error=error,
    )


def check(*entries: tuple[str, bool] | dict[str, Any]) -> AIMessage:
    rows = [
        e if isinstance(e, dict) else {"claim_id": e[0], "supported": e[1], "reason": "r"}
        for e in entries
    ]
    return AIMessage(
        content="",
        tool_calls=[{"name": "SelfCheck", "args": {"checks": rows}, "id": "call_1"}],
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )


def fix(claim_id: str, value: float, **more: Any) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "supported": False,
        "corrected_value": value,
        "reason": "fix",
        **more,
    }


def with_revisions(n: int) -> Config:
    return V1.model_copy(
        update={"verification": V1.verification.model_copy(update={"max_revisions": n})}
    )


def make(tmp_path: Path, *replies: Any, cfg: Config = V1) -> tuple[SelfCheckVerifier, Recording]:
    chat = Recording(*replies)
    llm = LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=lambda _: None)
    return SelfCheckVerifier(cfg, llm, questions={"q1": "What was 3M's capex growth?"}), chat


ALL_OK = check(("c1", True), ("c2", True), ("c3", True))


# --- Prompt and inputs --------------------------------------------------------------------------


def test_prompt_files_exist_and_fill() -> None:
    system = (PROMPTS_DIR / "v1_system.txt").read_text(encoding="utf-8")
    assert "SelfCheck" in system and "in millions" in system and "recompute" in system
    user = (PROMPTS_DIR / "v1_user.txt").read_text(encoding="utf-8")
    for field in ("$question", "$answer_text", "$claims", "$excerpts"):
        assert field in user


def test_claims_and_cited_excerpts_are_shown(tmp_path: Path) -> None:
    text = format_claims(claims())
    assert "- c1: capex = 1.577e+09 USD, FY2018; cites k1" in text
    assert (
        "- c3: capex growth = 14.86 %, FY2018; computed as (c1 - c2) / c2 * 100 from c1, c2" in text
    )
    excerpts = cited_excerpts(draft(), claims())
    assert excerpts.count("[k1]") == 1 and "table in millions" in excerpts
    missing = claims()[0].model_copy(update={"chunk_ids": ["k9"]})
    assert "[k9] (not in the evidence)" in cited_excerpts(draft(), [missing])

    verifier, chat = make(tmp_path, ALL_OK)
    verifier(draft(), V1)
    sent = str(chat.seen[0][1].content)
    assert "What was 3M's capex growth?" in sent and "Capex grew 14.9%" in sent
    assert "[k1] MMM 10-K FY2018, Item 8, table in millions" in sent
    assert chat.choices == ["SelfCheck"]


# --- Outcomes -----------------------------------------------------------------------------------


def test_all_supported_changes_nothing(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path, ALL_OK)
    r = verifier(draft(), V1)
    assert r.error is None and r.verification_arm == "self_check"
    assert r.claims_after == r.claims_before == claims()
    assert r.revisions_used == 0 and r.flagged_claim_ids == [] and chat.calls == 1
    assert [v.ok for v in r.verdicts] == [True, True, True]
    assert all(v.check == "self_check" and v.reason.startswith("round 1:") for v in r.verdicts)
    assert (r.tokens_in, r.tokens_out) == (100, 20)


def test_a_wrong_scale_is_corrected_then_rechecked(tmp_path: Path) -> None:
    replies = [
        check(fix("c1", 1_577_000_000.0), ("c2", True), ("c3", True)),
        ALL_OK,
    ]
    verifier, chat = make(tmp_path, *replies)
    r = verifier(draft(claims(capex=1577.0)), V1)
    assert r.claims_before[0].value == 1577.0  # what the draft said is kept
    assert r.claims_after[0].value == 1_577_000_000.0
    assert r.claims_after[1:] == r.claims_before[1:]
    assert r.revisions_used == 1 and r.flagged_claim_ids == [] and chat.calls == 2
    assert "1.577e+09" in str(chat.seen[1][1].content)  # the second check sees the revision
    assert (r.tokens_in, r.tokens_out) == (200, 40)


def test_unit_and_period_can_be_corrected_ids_and_citations_cannot() -> None:
    cs = claims()
    checks = self_check.SelfCheck.model_validate(
        {"checks": [fix("c3", 0.1486, corrected_unit="ratio", corrected_period="FY2017")]}
    ).checks
    out, changed = apply(cs, checks)
    assert changed
    assert (out[2].value, out[2].unit, out[2].period) == (0.1486, "ratio", "FY2017")
    assert (out[2].claim_id, out[2].chunk_ids, out[2].expression) == (
        "c3",
        [],
        "(c1 - c2) / c2 * 100",
    )


def test_unsupported_without_a_correction_is_flagged_not_changed(tmp_path: Path) -> None:
    unsupported = {"claim_id": "c2", "supported": False, "reason": "not in the excerpt"}
    verifier, chat = make(tmp_path, check(("c1", True), unsupported, ("c3", True)))
    r = verifier(draft(), V1)
    assert r.claims_after == r.claims_before and r.flagged_claim_ids == ["c2"]
    assert r.revisions_used == 0 and chat.calls == 1


def test_revisions_stop_at_the_limit_and_the_last_check_only_flags(tmp_path: Path) -> None:
    keeps_changing = [check(fix("c1", float(v))) for v in (1, 2, 3)]
    verifier, chat = make(tmp_path, *keeps_changing, cfg=with_revisions(2))
    r = verifier(draft(), with_revisions(2))
    assert chat.calls == 3 and r.revisions_used == 2
    assert r.claims_after[0].value == 2.0  # the third check's correction is not applied
    assert r.flagged_claim_ids == ["c1"]


def test_no_revisions_allowed_means_one_check_that_only_flags(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path, check(fix("c1", 5.0)), cfg=with_revisions(0))
    r = verifier(draft(), with_revisions(0))
    assert chat.calls == 1 and r.revisions_used == 0
    assert r.claims_after == r.claims_before and r.flagged_claim_ids == ["c1"]


def test_unknown_claim_ids_in_the_reply_are_ignored(tmp_path: Path) -> None:
    verifier, _ = make(tmp_path, check(("c1", True), fix("c9", 1.0)))
    r = verifier(draft(), V1)
    assert r.claims_after == r.claims_before and r.flagged_claim_ids == []
    assert [v.claim_id for v in r.verdicts] == ["c1"]


# --- Drafts it skips, and failures ----------------------------------------------------------


@pytest.mark.parametrize("d", [draft(error="ValidationError: x"), draft(cs=[])])
def test_failed_or_empty_drafts_are_not_checked(tmp_path: Path, d: Draft) -> None:
    verifier, chat = make(tmp_path)
    r = verifier(d, V1)
    assert chat.calls == 0 and r.claims_after == r.claims_before and r.error is None


@pytest.mark.parametrize(
    "reply, expected",
    [
        (
            AIMessage(
                content="looks fine",
                usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            ),
            "ValueError",
        ),
        (check({"claim_id": "c1", "reason": "missing supported"}), "ValidationError"),
        (check(fix("c1", 1.0, corrected_unit="stores")), "ValidationError"),
    ],
)
def test_a_reply_that_does_not_validate_is_the_results_error(
    tmp_path: Path, reply: AIMessage, expected: str
) -> None:
    verifier, _ = make(tmp_path, reply)
    r = verifier(draft(), V1)
    assert r.error is not None and r.error.startswith(expected)
    assert r.claims_after == r.claims_before


def test_a_refused_request_is_raised_for_the_runner(tmp_path: Path) -> None:
    verifier, _ = make(tmp_path, bad_request())
    with pytest.raises(Exception, match="tool_use_failed"):
        verifier(draft(), V1)  # the runner records it as a failed verification


def test_rerun_replays_from_the_cache(tmp_path: Path) -> None:
    replies = [check(fix("c1", 1_577_000_000.0), ("c2", True), ("c3", True)), ALL_OK]
    verifier, chat = make(tmp_path, *replies)
    first = verifier(draft(claims(capex=1577.0)), V1)
    second = verifier(draft(claims(capex=1577.0)), V1)
    assert chat.calls == 2 and second.claims_after == first.claims_after


def test_rejects_other_arms(tmp_path: Path) -> None:
    v0 = load_config(CONFIGS_DIR / "grid" / "r0_v0.yaml")
    with pytest.raises(ValueError, match="not V1"):
        SelfCheckVerifier(v0, LLM(v0, Recording(), cache_dir=tmp_path))


def test_matches_the_runner_interface() -> None:
    import inspect

    from finqa.eval import runner

    assert runner.resolve(runner.VERIFIERS, "self_check") is self_check.verify
    assert list(inspect.signature(self_check.verify).parameters) == ["draft", "cfg"]
