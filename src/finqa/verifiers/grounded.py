"""V2: grounded verification (ROADMAP P4.3-P4.6, guide §4.3).

Per claim, up to three rule-based checks, each recording a `Verdict` (`ok=None` when the check
cannot run). A claim fails if any check that ran returns `ok=False`. No model judges a claim.

Check 1, cited text (P4.3): does a chunk the claim cites state the claimed value? Numbers are
read with the shared reader (finqa.verifiers.numbers) and put in full units with the chunk's
`unit_scale`; values match within `verification.tolerance` (relative), ignoring sign, because
filings print outflows in parentheses (same as the citation diagnostic, DECISIONS 2026-11-08).

Scale rule (DECISIONS 2026-11-22): a bare number in a table with a stated `unit_scale` counts
only at that scale for a USD claim, so "1,577" in a table "in millions" supports
1,577,000,000 USD and not 1,577 USD (a scale error). For other units the raw value is also
tried, because tables are "in millions, except per share" and may state shares, ratios or
days unscaled. A number with its own scale ("$1.6 billion") or a percentage is never rescaled.

A claim with an `expression` is computed, not quoted: check 1 does not run (check 3 does). A
quoted claim that cites nothing, or cites only chunks the draft never retrieved, fails: V2
accepts a number only if it is grounded in the evidence.

Check 2, XBRL (P4.4): the company's XBRL value for the claim's metric and period. The claim's
metric name is mapped to a `data/metric_map.yaml` metric through that file's aliases
(finqa.ingestion.xbrl.metric_for). It runs only when the name is mapped, the units agree, the
company is known and XBRL has a value for that period; otherwise `ok=None`, never a failure
(a missing mapping is not evidence of an error). Any reported value (restatements give
several) within tolerance, ignoring sign, passes. XBRL is evidence for the verifier here; it
never decides correctness, which is scored against FinanceBench gold (ROADMAP rule 10).

A table that states no scale (`unit_scale` None) gives no basis for the scale rule, so a bare
number in it is tried as units, thousands, millions and billions (DECISIONS 2026-11-23);
prose numbers carry their own scale words and are read as written.

Check 3, recomputation (P4.5): a computed claim's `expression` evaluated on the current values
of its `derived_from` claims (finqa.eval.error_types.recompute: variables are claim IDs or
a, b, c... in order). A % claim passes if it matches the result either as computed or times
100, since models write a percent both as "c1 / c2" and as "c1 / c2 * 100". The result must
be within tolerance, sign included, since a sign is part of a computation. A quoted claim gets
`ok=None`. A computed claim that cannot be recomputed (no inputs, an input that is not a
claim, or an expression that does not evaluate) fails, for the same reason an uncited quoted
claim fails check 1: V2 accepts only numbers it can trace to the evidence.

Revision loop (P4.6, guide §4.4; DECISIONS 2026-11-23): every claim gets all three checks. The
claims that fail go back to the same model with one feedback line per failed claim (each
failed check's reason) and the excerpts the claims cite, and it fills in a `Revision` form:
a corrected value, unit and period per failed claim, the same correction form as V1, so V1 and
V2 differ only in what finds the errors (the model itself, or the rules). Corrections are
applied and every claim is checked again, up to `verification.max_revisions` revisions; the
claims still failing are flagged. A claim whose only failure is that it cites nothing the draft
retrieved is flagged but not sent for revision: there is no excerpt to correct it against,
and a revision cannot add citations (DECISIONS 2026-11-23). Claim IDs, metrics, citations
and expressions stay as drafted, and the answer text is not rewritten (scoring reads the
draft's; scoring.py).
Prompts: v2_system.txt, v2_user.txt (to be frozen before any test-split run).
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Sequence
from string import Template

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from finqa.config import Config
from finqa.eval.citation_check import _HAS_SCALE
from finqa.eval.error_types import Lookup, recompute, xbrl_lookup
from finqa.eval.scoring import within_tolerance
from finqa.generators.common import load_prompt
from finqa.ingestion.xbrl import Metric, load_metric_map, metric_for
from finqa.llm import LLM
from finqa.schemas import Chunk, Claim, Draft, Period, Unit, Verdict, VerifiedResult
from finqa.verifiers.base import result
from finqa.verifiers.numbers import extract_numbers
from finqa.verifiers.self_check import ClaimCheck, apply, cited_excerpts, format_claims

CITED_TEXT = "cited_text"
XBRL = "xbrl"
RECOMPUTE = "recompute"
NO_CITATION = "cites no evidence"
NOT_RETRIEVED = ", which is not in the retrieved evidence"
ARM = "grounded"
SYSTEM_PROMPT = "v2_system.txt"
USER_PROMPT = "v2_user.txt"

# question_id -> (question text, the CIK of the question's company or None)
Context = Callable[[str], tuple[str, str | None]]


UNSTATED_SCALES = (1.0, 1e3, 1e6, 1e9)  # a table that states no scale could be in any


def chunk_values(chunk: Chunk, unit: Unit) -> list[float]:
    """The values `chunk` states, in full units and absolute, as candidates for a claim in
    `unit` (the scale rule above)."""
    values: list[float] = []
    for p in extract_numbers(chunk.text):
        raw = abs(p.value)
        if p.unit == "%" or _HAS_SCALE.search(p.text) or not chunk.is_table:
            values.append(raw)
        elif not chunk.unit_scale:
            values += [raw * s for s in UNSTATED_SCALES]
        else:
            scaled = raw * chunk.unit_scale
            values += [scaled] if unit == "USD" else [raw, scaled]
    return values


def check_cited_text(claim: Claim, draft: Draft, tolerance: float) -> Verdict:
    def verdict(ok: bool | None, reason: str) -> Verdict:
        return Verdict(claim_id=claim.claim_id, ok=ok, check=CITED_TEXT, reason=reason)

    if claim.expression:
        return verdict(None, "computed claim: checked by recomputation")
    if not claim.chunk_ids:
        return verdict(False, NO_CITATION)
    cited = [draft.evidence[k] for k in claim.chunk_ids if k in draft.evidence]
    if not cited:
        missing = ", ".join(claim.chunk_ids)
        return verdict(False, f"cites {missing}{NOT_RETRIEVED}")
    target = abs(claim.value)
    for chunk in cited:
        if any(within_tolerance(target, v, tolerance) for v in chunk_values(chunk, claim.unit)):
            return verdict(True, f"{claim.value:g} {claim.unit} is stated in {chunk.chunk_id}")
    where = ", ".join(c.chunk_id for c in cited)
    scale = next((c.unit_scale for c in cited if c.unit_scale), None)
    hint = f" (table in units of {scale:g})" if scale else ""
    if not scale and any(c.is_table for c in cited):
        hint = " (table scale not stated; tried units, thousands, millions, billions)"
    return verdict(False, f"{claim.value:g} {claim.unit} is not stated in {where}{hint}")


def check_xbrl(
    claim: Claim,
    cik: str | None,
    tolerance: float,
    metric_map: dict[str, Metric],
    lookup: Lookup = xbrl_lookup,
) -> Verdict:
    def verdict(ok: bool | None, reason: str) -> Verdict:
        return Verdict(claim_id=claim.claim_id, ok=ok, check=XBRL, reason=reason)

    metric = metric_for(claim.metric, metric_map)
    if metric is None:
        return verdict(None, f"metric {claim.metric!r} has no XBRL mapping")
    if metric_map[metric].unit != claim.unit:
        return verdict(None, f"{metric} is in {metric_map[metric].unit}, the claim in {claim.unit}")
    if cik is None:
        return verdict(None, "company not known")
    values = lookup(cik, metric, claim.period)
    if not values:
        return verdict(None, f"no XBRL value for {metric} {claim.period}")
    target = abs(claim.value)
    if any(within_tolerance(target, abs(v), tolerance) for v in values):
        return verdict(True, f"matches XBRL {metric} {claim.period}")
    reported = ", ".join(f"{v:g}" for v in _distinct(values)[:3])
    return verdict(
        False, f"XBRL {metric} {claim.period} is {reported} {claim.unit}, not {claim.value:g}"
    )


def _distinct(values: list[float]) -> list[float]:
    out: list[float] = []
    for v in values:
        if not any(abs(v - w) <= 0.001 * max(abs(w), 1.0) for w in out):
            out.append(v)
    return out


def check_recompute(claim: Claim, claims: Sequence[Claim], tolerance: float) -> Verdict:
    def verdict(ok: bool | None, reason: str) -> Verdict:
        return Verdict(claim_id=claim.claim_id, ok=ok, check=RECOMPUTE, reason=reason)

    if not claim.expression:
        return verdict(None, "quoted claim: nothing to recompute")
    if not claim.derived_from:
        return verdict(False, f"{claim.expression} names no input claims")
    ids = {c.claim_id for c in claims}
    missing = [i for i in claim.derived_from if i not in ids]
    if missing:
        return verdict(False, f"inputs {', '.join(missing)} are not claims in the draft")
    # the expression's own result, without error typing's fraction-to-percent guess
    result = recompute(claim.model_copy(update={"unit": "ratio"}), claims)
    if result is None:
        return verdict(False, f"{claim.expression} cannot be evaluated on its inputs")
    # a % claim may be computed as a fraction ("c1 / c2") or as a percent ("c1 / c2 * 100")
    candidates = [result, result * 100] if claim.unit == "%" else [result]
    if any(within_tolerance(claim.value, r, tolerance) for r in candidates):
        return verdict(True, f"{claim.expression} = {result:g}")
    # report the reading nearest the claim, so the feedback names the figure meant
    nearest = min(candidates, key=lambda r: abs(r - claim.value))
    return verdict(False, f"{claim.expression} = {nearest:g}, not {claim.value:g}")


# --- The verifier: checks, feedback, revision -----------------------------------------------


class ClaimFix(BaseModel):
    claim_id: str
    corrected_value: float | None = Field(default=None, description="full units; null if right")
    corrected_unit: Unit | None = None
    corrected_period: Period | None = None
    reason: str = Field(description="one short sentence")


class Revision(BaseModel):
    """Your corrections to the claims that failed the check."""

    fixes: list[ClaimFix]


def failed(verdicts: Sequence[Verdict]) -> list[str]:
    """IDs of the claims with at least one check that ran and failed, in verdict order."""
    out: list[str] = []
    for v in verdicts:
        if v.ok is False and v.claim_id not in out:
            out.append(v.claim_id)
    return out


def uncited(v: Verdict) -> bool:
    """A cited-text failure because the claim cites nothing it retrieved: no excerpt to
    correct it against, and a revision cannot add citations."""
    return v.check == CITED_TEXT and (v.reason == NO_CITATION or v.reason.endswith(NOT_RETRIEVED))


def revisable(verdicts: Sequence[Verdict]) -> list[str]:
    """Failed claims worth a revision: those with a failure other than an uncited one
    (DECISIONS 2026-11-23). Uncited claims stay failed and are flagged."""
    out: list[str] = []
    for v in verdicts:
        if v.ok is False and not uncited(v) and v.claim_id not in out:
            out.append(v.claim_id)
    return out


CHECK_NAMES = {CITED_TEXT: "cited text", XBRL: "XBRL", RECOMPUTE: "recomputation"}


def feedback(verdicts: Sequence[Verdict]) -> str:
    """One line per claim to revise: what each of its failed checks found."""
    lines = []
    for claim_id in revisable(verdicts):
        reasons = [
            f"{CHECK_NAMES[v.check]}: {v.reason}"
            for v in verdicts
            if v.claim_id == claim_id and v.ok is False
        ]
        lines.append(f"- {claim_id}: " + "; ".join(reasons))
    return "\n".join(lines)


class GroundedVerifier:
    def __init__(
        self,
        cfg: Config,
        llm: LLM,
        context: Context | None = None,
        metric_map: dict[str, Metric] | None = None,
        lookup: Lookup = xbrl_lookup,
    ) -> None:
        if cfg.verification.arm != ARM:
            raise ValueError(f"config {cfg.name!r} is not V2: {cfg.verification.arm!r}")
        self.cfg = cfg
        self.llm = llm
        self._context = context
        self.metric_map = metric_map if metric_map is not None else load_metric_map()
        self.lookup = lookup

    def context(self, question_id: str) -> tuple[str, str | None]:
        if self._context is None:
            self._context = _financebench_context()
        return self._context(question_id)

    def check(self, draft: Draft, claims: list[Claim], cik: str | None) -> list[Verdict]:
        """All three checks on every claim, claim by claim."""
        tol = self.cfg.verification.tolerance
        out: list[Verdict] = []
        for c in claims:
            out += [
                check_cited_text(c, draft, tol),
                check_xbrl(c, cik, tol, self.metric_map, self.lookup),
                check_recompute(c, claims, tol),
            ]
        return out

    def revise(
        self, draft: Draft, claims: list[Claim], verdicts: list[Verdict], question: str
    ) -> tuple[Revision, int, int]:
        prompt = [
            SystemMessage(load_prompt(SYSTEM_PROMPT)),
            HumanMessage(
                Template(load_prompt(USER_PROMPT)).substitute(
                    question=question,
                    answer_text=draft.answer_text,
                    claims=format_claims(claims),
                    feedback=feedback(verdicts),
                    excerpts=cited_excerpts(draft, claims),
                )
            ),
        ]
        response = self.llm.invoke(
            prompt, tools=[Revision], tool_choice="Revision", question_id=draft.question_id
        )
        usage = response.usage_metadata
        tokens = (usage["input_tokens"], usage["output_tokens"]) if usage else (0, 0)
        if not response.tool_calls:
            raise ValueError("no Revision tool call in response")
        return Revision.model_validate(response.tool_calls[0]["args"]), *tokens

    def __call__(self, draft: Draft, cfg: Config) -> VerifiedResult:
        started = time.monotonic()
        if draft.error is not None or not draft.claims:
            return result(draft, cfg)
        question, cik = self.context(draft.question_id)
        claims = list(draft.claims)
        verdicts: list[Verdict] = []
        failing: list[str] = []
        revisions, tokens_in, tokens_out = 0, 0, 0
        try:
            while True:
                round_verdicts = self.check(draft, claims, cik)
                verdicts += [
                    v.model_copy(update={"reason": f"round {revisions + 1}: {v.reason}"})
                    for v in round_verdicts
                ]
                failing = failed(round_verdicts)
                to_revise = revisable(round_verdicts)
                if not to_revise or revisions >= cfg.verification.max_revisions:
                    break  # nothing to revise, or out of revisions: what fails is flagged
                revision, t_in, t_out = self.revise(draft, claims, round_verdicts, question)
                tokens_in, tokens_out = tokens_in + t_in, tokens_out + t_out
                fixes = [
                    ClaimCheck(supported=False, **f.model_dump())
                    for f in revision.fixes
                    if f.claim_id in to_revise
                ]
                revised, changed = apply(claims, fixes)
                if not changed:
                    break  # the model kept its claims: they stay flagged
                claims, revisions = revised, revisions + 1
        except (ValidationError, ValueError) as e:
            return result(
                draft,
                cfg,
                latency_s=round(time.monotonic() - started, 3),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=f"{type(e).__name__}: {e}",
            )
        return result(
            draft,
            cfg,
            claims_after=claims,
            verdicts=verdicts,
            revisions_used=revisions,
            flagged_claim_ids=failing,
            latency_s=round(time.monotonic() - started, 3),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


def _financebench_context() -> Context:
    """question_id -> (question text, CIK of the question's company), from FinanceBench and the
    company resolver (offline: companies.csv)."""
    from finqa.ingestion import financebench
    from finqa.tools.resolver import CompanyResolver

    records = {r["financebench_id"]: r for r in financebench.load()}
    resolver = CompanyResolver.from_csv()

    def context(question_id: str) -> tuple[str, str | None]:
        r = records.get(question_id)
        if r is None:
            return "(question text not available)", None
        company = resolver.resolve(r["company"]).company
        return r["question"], company.cik if company else None

    return context


@functools.cache
def _verifier(cfg: Config) -> GroundedVerifier:
    return GroundedVerifier(cfg, LLM(cfg))


def verify(draft: Draft, cfg: Config) -> VerifiedResult:
    """The runner's entry point for the "grounded" arm (finqa.eval.runner.VERIFIERS)."""
    return _verifier(cfg)(draft, cfg)
