"""Agreement between two runs of the same config on the same dev questions.

Used before the model-serving switch (Groq vs a self-hosted vLLM copy of the same weights):

    uv run python scripts/compare_runs.py --a <groq dev run> --b <vllm dev run>

Both runs are scored against gold with one judge, the frozen judge on configs/base.yaml's model,
so differences come only from the generator's serving. Writes
runs/{b}/agreement_vs_{a}.md: a per-question table (outcome and answer of each run), outcome
and answer agreement counts, and the paired McNemar table. Dev only: comparing on test would
mean looking at test results to pick a server.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from finqa.config import CONFIGS_DIR, Config, load_config
from finqa.eval import tables
from finqa.eval.questions import load_questions
from finqa.eval.runner import RUNS_DIR, RunRefused, read_jsonl
from finqa.eval.scoring import Gold, Judge, load_gold
from finqa.generators.base import Question
from finqa.schemas import Draft

BASE_CONFIG = CONFIGS_DIR / "base.yaml"


def answer_value(d: Draft) -> str:
    """The answer claim as `value unit`, or a short marker when there is none."""
    if d.error is not None:
        return "failed"
    claim = next((c for c in d.claims if c.claim_id == d.answer_claim_id), None)
    if claim is None:
        return "text" if d.answer_text.strip() else "none"
    return f"{claim.value:g} {claim.unit}"


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def agreement_report(
    name_a: str,
    drafts_a: Sequence[Draft],
    rows_a: Sequence[tables.Row],
    name_b: str,
    drafts_b: Sequence[Draft],
    rows_b: Sequence[tables.Row],
) -> str:
    """Markdown: per-question outcomes and answers, agreement counts, paired McNemar."""
    da = {d.question_id: d for d in drafts_a}
    db = {d.question_id: d for d in drafts_b}
    ra = {r.question_id: r for r in rows_a}
    rb = {r.question_id: r for r in rows_b}
    if ra.keys() != rb.keys():
        raise RunRefused("the two runs cover different questions; finish both first")
    ids = sorted(ra)
    same_outcome = sum(ra[q].outcome == rb[q].outcome for q in ids)
    same_answer = sum(answer_value(da[q]) == answer_value(db[q]) for q in ids)
    same_text = sum(da[q].answer_text.strip() == db[q].answer_text.strip() for q in ids)
    n = len(ids)
    failed_a = sum(da[q].error is not None for q in ids)
    failed_b = sum(db[q].error is not None for q in ids)
    lines = [f"## {name_a} vs {name_b}\n"]
    if failed_a or failed_b:
        lines.append(
            f"**WARNING: failed drafts ({name_a}: {failed_a}/{n}, {name_b}: {failed_b}/{n}). "
            "A failure scores as incorrect, so outcome agreement below overstates real "
            "agreement; fix the failures and rerun before using this comparison.**\n"
        )
    lines += [
        f"Same outcome: {same_outcome}/{n}. Same answer claim (value and unit): {same_answer}/{n}. "
        f"Identical answer text: {same_text}/{n}.\n",
        tables.comparison_table(name_a, rows_a, name_b, rows_b),
        f"| Question | Type | {name_a} outcome | {name_b} outcome | {name_a} answer "
        f"| {name_b} answer | Same outcome |",
        "|---|---|---|---|---|---|---|",
    ]
    for q in ids:
        lines.append(
            f"| {q} | {ra[q].question_type} | {ra[q].outcome} | {rb[q].outcome} "
            f"| {_cell(answer_value(da[q]))} | {_cell(answer_value(db[q]))} "
            f"| {'yes' if ra[q].outcome == rb[q].outcome else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def _run_meta(run_dir: Path) -> dict[str, object]:
    path = run_dir / "run_meta.json"
    if not path.exists():
        raise RunRefused(f"no run {run_dir.name} in {run_dir.parent}")
    meta: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return meta


def default_judge(cfg: Config, run_id: str) -> Judge:
    from finqa.eval.scoring import llm_judge
    from finqa.llm import LLM

    return llm_judge(LLM(cfg), run_id)


def compare_command(
    run_a: str,
    run_b: str,
    runs_dir: Path = RUNS_DIR,
    questions: dict[str, Question] | None = None,
    gold: dict[str, Gold] | None = None,
    make_judge: Callable[[Config, str], Judge] = default_judge,
    judge_config: Path = BASE_CONFIG,
) -> int:
    metas = {r: _run_meta(runs_dir / r) for r in (run_a, run_b)}
    if any(m["split"] != "dev" for m in metas.values()):
        raise RunRefused("the agreement check is dev only")
    questions = questions or {q.question_id: q for q in load_questions("dev")}
    gold = gold or load_gold()
    judge_cfg = load_config(judge_config, BASE_CONFIG)
    drafts: dict[str, list[Draft]] = {}
    rows: dict[str, list[tables.Row]] = {}
    for r in (run_a, run_b):
        drafts[r] = read_jsonl(runs_dir / r / "drafts.jsonl", Draft)
        cfg = Config.model_validate(metas[r]["config"])
        rows[r] = tables.score_run(
            drafts[r], questions, gold, cfg.verification.tolerance, make_judge(judge_cfg, r)
        )
    report = agreement_report(run_a, drafts[run_a], rows[run_a], run_b, drafts[run_b], rows[run_b])
    out = runs_dir / run_b / f"agreement_vs_{run_a}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"-> {out}")
    return 0
