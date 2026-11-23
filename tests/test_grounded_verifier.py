"""V2 grounded verifier with its revision loop (ROADMAP P4.6), with a fake chat model."""

import inspect
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from test_agent import Recording

from finqa.config import CONFIGS_DIR, Config, Secrets, load_config
from finqa.generators.common import PROMPTS_DIR
from finqa.ingestion.xbrl import load_metric_map
from finqa.llm import LLM
from finqa.schemas import Chunk, Claim, Draft
from finqa.verifiers import grounded
from finqa.verifiers.grounded import GroundedVerifier, failed, feedback

V2 = load_config(CONFIGS_DIR / "grid" / "r0_v2.yaml")
MMM = "0000066740"
TABLE = Chunk(
    chunk_id="k1",
    cik=MMM,
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


def claims(capex: float = 1.577e9, growth: float = 14.86) -> list[Claim]:
    return [
        Claim(
            claim_id="c1",
            metric="capital expenditures",
            value=capex,
            unit="USD",
            period="FY2018",
            chunk_ids=["k1"],
        ),
        Claim(
            claim_id="c2",
            metric="capital expenditures",
            value=1.373e9,
            unit="USD",
            period="FY2017",
            chunk_ids=["k1"],
        ),
        Claim(
            claim_id="c3",
            metric="capex growth",
            value=growth,
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


XBRL_FACTS = {(MMM, "capital_expenditure", "FY2018"): [1.577e9]}


def lookup(cik: str, metric: str, period: str) -> list[float]:
    return XBRL_FACTS.get((cik, metric, period), [])


def revision(*fixes: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "Revision", "args": {"fixes": list(fixes)}, "id": "call_1"}],
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )


def fix(claim_id: str, value: float, **more: Any) -> dict[str, Any]:
    return {"claim_id": claim_id, "corrected_value": value, "reason": "fix", **more}


def with_revisions(n: int) -> Config:
    return V2.model_copy(
        update={"verification": V2.verification.model_copy(update={"max_revisions": n})}
    )


def make(
    tmp_path: Path, *replies: Any, cfg: Config = V2, cik: str | None = MMM
) -> tuple[GroundedVerifier, Recording]:
    chat = Recording(*replies)
    llm = LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=lambda _: None)
    verifier = GroundedVerifier(
        cfg,
        llm,
        context=lambda qid: ("What was 3M's capex growth in FY2018?", cik),
        metric_map=load_metric_map(),
        lookup=lookup,
    )
    return verifier, chat


# --- Prompts ----------------------------------------------------------------------------------


def test_prompt_files_exist_and_fill() -> None:
    system = (PROMPTS_DIR / "v2_system.txt").read_text(encoding="utf-8")
    assert "Revision" in system and "in millions" in system and "XBRL" in system
    user = (PROMPTS_DIR / "v2_user.txt").read_text(encoding="utf-8")
    for field in ("$question", "$answer_text", "$claims", "$feedback", "$excerpts"):
        assert field in user


# --- The acceptance case: a planted error corrected in one round -------------------------------


def test_a_planted_scale_error_is_corrected_in_one_round(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path, revision(fix("c1", 1.577e9)))
    r = verifier(draft(claims(capex=1577.0)), V2)
    assert r.claims_before[0].value == 1577.0
    assert r.claims_after == claims()  # c1 fixed; c3 now recomputes to 14.86
    assert r.revisions_used == 1 and r.flagged_claim_ids == [] and chat.calls == 1
    assert r.error is None and r.verification_arm == "grounded"
    sent = str(chat.seen[0][1].content)
    assert "What was 3M's capex growth in FY2018?" in sent
    assert "- c1: cited text: 1577 USD is not stated in k1 (table in units of 1e+06)" in sent
    assert "XBRL: XBRL capital_expenditure FY2018 is 1.577e+09 USD, not 1577" in sent
    assert "- c3: recomputation: (c1 - c2) / c2 * 100 = -99.9999" in sent
    assert "[k1] MMM 10-K FY2018, Item 8, table in millions" in sent
    assert chat.choices == ["Revision"]
    # round 1 and round 2 verdicts, three checks per claim each
    assert len(r.verdicts) == 2 * 3 * 3
    assert {v.reason.split(":")[0] for v in r.verdicts} == {"round 1", "round 2"}
    assert (r.tokens_in, r.tokens_out) == (100, 20)


def test_all_passing_claims_need_no_model_call(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path)
    r = verifier(draft(), V2)
    assert chat.calls == 0 and r.revisions_used == 0 and r.flagged_claim_ids == []
    assert r.claims_after == r.claims_before
    by_check = {(v.claim_id, v.check): v.ok for v in r.verdicts}
    assert by_check == {
        ("c1", "cited_text"): True,
        ("c1", "xbrl"): True,
        ("c1", "recompute"): None,
        ("c2", "cited_text"): True,
        ("c2", "xbrl"): None,  # no FY2017 value in the fake XBRL
        ("c2", "recompute"): None,
        ("c3", "cited_text"): None,
        ("c3", "xbrl"): None,  # "capex growth" is not mapped
        ("c3", "recompute"): True,
    }


def test_the_company_comes_from_the_question(tmp_path: Path) -> None:
    verifier, _ = make(tmp_path, cik=None)
    r = verifier(draft(), V2)
    xbrl = [v for v in r.verdicts if v.check == "xbrl" and v.claim_id == "c1"]
    assert xbrl[0].ok is None and "company not known" in xbrl[0].reason


# --- What the loop does with the model's revision ----------------------------------------------


def test_fixes_to_claims_that_passed_are_ignored(tmp_path: Path) -> None:
    one = with_revisions(1)
    verifier, _ = make(tmp_path, revision(fix("c2", 5.0), fix("c3", 99.0)), cfg=one)
    r = verifier(draft(claims(growth=12.0)), one)  # only c3 fails
    assert r.claims_after[1].value == 1.373e9  # c2 passed, its "fix" is ignored
    assert r.claims_after[2].value == 99.0 and r.flagged_claim_ids == ["c3"]


def test_a_model_that_keeps_its_claims_leaves_them_flagged(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path, revision())
    r = verifier(draft(claims(growth=12.0)), V2)
    assert chat.calls == 1 and r.revisions_used == 0
    assert r.claims_after == r.claims_before and r.flagged_claim_ids == ["c3"]


def test_revisions_stop_at_the_limit_and_failures_are_flagged(tmp_path: Path) -> None:
    replies = [revision(fix("c3", v)) for v in (13.0, 13.5)]
    verifier, chat = make(tmp_path, *replies, cfg=with_revisions(2))
    r = verifier(draft(claims(growth=12.0)), with_revisions(2))
    assert chat.calls == 2 and r.revisions_used == 2
    assert r.claims_after[2].value == 13.5 and r.flagged_claim_ids == ["c3"]
    assert len(r.verdicts) == 3 * 3 * 3  # three rounds of checks


def test_no_revisions_allowed_means_check_and_flag_only(tmp_path: Path) -> None:
    verifier, chat = make(tmp_path, cfg=with_revisions(0))
    r = verifier(draft(claims(capex=1577.0)), with_revisions(0))
    assert chat.calls == 0 and r.flagged_claim_ids == ["c1", "c3"]


def test_feedback_lists_each_failed_check_once_per_claim() -> None:
    verifier = GroundedVerifier(
        V2, LLM(V2, Recording()), context=lambda q: ("", MMM), lookup=lookup
    )
    verdicts = verifier.check(draft(), claims(capex=1577.0), MMM)
    assert failed(verdicts) == ["c1", "c3"]
    lines = feedback(verdicts).splitlines()
    assert len(lines) == 2 and lines[0].startswith("- c1: cited text: ")
    assert "; XBRL: " in lines[0] and lines[1].startswith("- c3: recomputation: ")


# --- Drafts it skips, and failures ----------------------------------------------------------


@pytest.mark.parametrize("d", [draft(error="ValidationError: x"), draft(cs=[])])
def test_failed_or_empty_drafts_are_not_checked(tmp_path: Path, d: Draft) -> None:
    verifier, chat = make(tmp_path)
    r = verifier(d, V2)
    assert chat.calls == 0 and r.claims_after == r.claims_before and r.verdicts == []


@pytest.mark.parametrize(
    "reply, expected",
    [
        (
            AIMessage(
                content="fixed",
                usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            ),
            "ValueError",
        ),
        (revision(fix("c1", 1.0, corrected_unit="stores")), "ValidationError"),
    ],
)
def test_a_revision_that_does_not_validate_is_the_results_error(
    tmp_path: Path, reply: AIMessage, expected: str
) -> None:
    verifier, _ = make(tmp_path, reply)
    r = verifier(draft(claims(capex=1577.0)), V2)
    assert r.error is not None and r.error.startswith(expected)
    assert r.claims_after == r.claims_before


def test_rejects_other_arms(tmp_path: Path) -> None:
    v1 = load_config(CONFIGS_DIR / "grid" / "r0_v1.yaml")
    with pytest.raises(ValueError, match="not V2"):
        GroundedVerifier(v1, LLM(v1, Recording(), cache_dir=tmp_path))


def test_matches_the_runner_interface() -> None:
    from finqa.eval import runner

    assert runner.resolve(runner.VERIFIERS, "grounded") is grounded.verify
    assert list(inspect.signature(grounded.verify).parameters) == ["draft", "cfg"]


# --- The same acceptance case against the real model -----------------------------------------


@pytest.mark.integration
def test_real_model_corrects_a_planted_scale_error(tmp_path: Path) -> None:
    """Run on the cluster inside a serve_and_run job (VLLM_BASE_URL set by the job)."""
    if not Secrets().vllm_base_url:
        pytest.skip("needs the vLLM server (VLLM_BASE_URL)")
    llm = LLM(V2, cache_dir=tmp_path)
    verifier = GroundedVerifier(
        V2,
        llm,
        context=lambda q: ("What was 3M's FY2018 capital expenditure growth?", MMM),
        lookup=lookup,
    )
    r = verifier(draft(claims(capex=1577.0)), V2)
    assert r.error is None
    assert r.revisions_used == 1 and r.flagged_claim_ids == []
    assert r.claims_after[0].value == pytest.approx(1.577e9, rel=0.01)
