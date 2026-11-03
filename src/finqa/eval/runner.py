"""Runner: generators → drafts, verifiers → verified results (ROADMAP P2.2, guide §2.2).

    uv run finqa draft  --config configs/grid/r0_v0.yaml --split dev
    uv run finqa verify --run <run_id> --config configs/grid/r0_v1.yaml

Draft stage:  generator → runs/{run_id}/drafts.jsonl, one Draft per question, fresh thread each.
Verify stage: saved drafts + verifier → runs/{run_id}/verified_{arm}.jsonl.
Both stages append one line per question as soon as it is done and skip question IDs already
written, so a killed run resumes where it stopped. run_meta.json records the config, git commit,
model ID, thinking setting, date and package versions. Run IDs follow T13:
{date}_{config-name}_{short-commit}. A test-split run needs a clean working tree on `main` (T12).
A generator or verifier that raises is recorded with `error` set, never dropped.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from finqa.config import CONFIGS_DIR, Config, load_config
from finqa.eval.questions import SPLITS_PATH, load_questions
from finqa.generators.base import Generator, Question, RunContext
from finqa.ingestion import financebench
from finqa.schemas import Draft, VerifiedResult
from finqa.tracing import Tracer, trace_id_for

REPO_ROOT = CONFIGS_DIR.parent
RUNS_DIR = REPO_ROOT / "runs"

Verifier = Callable[[Draft, Config], VerifiedResult]
Model = TypeVar("Model", bound=BaseModel)

# Arm name → "module:function". Modules are imported only when their arm is used.
GENERATORS = {
    "closed_book": "finqa.generators.closed_book:generate",  # S0, P3.0
    "rag": "finqa.generators.rag:generate",  # R0, P3.5
    "agentic": "finqa.generators.agent:generate",  # R1, P3.6
}
VERIFIERS = {
    "none": "finqa.verifiers.none:verify",  # V0, P4.1
    "self_check": "finqa.verifiers.self_check:verify",  # V1, P4.2
    "grounded": "finqa.verifiers.grounded:verify",  # V2, P4.3-P4.6
}


class RunRefused(RuntimeError):
    """The run would break a rule (T12 test-split guard, mismatched config on resume)."""


@dataclass(frozen=True)
class GitState:
    commit: str
    short: str
    branch: str
    dirty: bool


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def git_state(cwd: Path = REPO_ROOT) -> GitState:
    commit = _git("rev-parse", "HEAD", cwd=cwd)
    return GitState(
        commit=commit,
        short=commit[:7],
        branch=_git("branch", "--show-current", cwd=cwd),
        dirty=bool(_git("status", "--porcelain", cwd=cwd)),
    )


def check_split_allowed(split: str, git: GitState) -> None:
    """T12: test-split runs only from a clean working tree on `main`."""
    if split != "test":
        return
    if git.dirty:
        raise RunRefused("test-split runs need a clean working tree (ROADMAP T12)")
    if git.branch != "main":
        raise RunRefused(f"test-split runs only from main, not {git.branch or 'a detached HEAD'}")


def make_run_id(config_name: str, git: GitState, today: date | None = None) -> str:
    """T13: {date}_{config-name}_{short-commit}, e.g. 2026-11-10_r0_v0_a1b2c3d."""
    return f"{(today or date.today()).isoformat()}_{config_name}_{git.short}"


def resolve(table: dict[str, str], arm: str) -> Any:
    """Import the function registered for `arm`."""
    if arm not in table:
        raise ValueError(f"no implementation registered for arm {arm!r}")
    module, _, name = table[arm].partition(":")
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError) as e:
        raise RunRefused(f"arm {arm!r} is not built yet ({table[arm]})") from e


def package_versions() -> dict[str, str]:
    return dict(sorted((d.metadata["Name"].lower(), d.version) for d in metadata.distributions()))


def run_meta(cfg: Config, split: str, git: GitState, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "config_name": cfg.name,
        "config": cfg.model_dump(),
        "split": split,
        "git_commit": git.commit,
        "git_branch": git.branch,
        "git_dirty": git.dirty,
        "model_id": cfg.model.id,
        "thinking": cfg.model.thinking,
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "package_versions": package_versions(),
    }


def read_jsonl(path: Path, model: type[Model]) -> list[Model]:
    """Every complete line of `path`. A half-written last line (a killed run) is cut off."""
    if not path.exists():
        return []
    rows: list[Model] = []
    good_bytes = 0
    with path.open("rb") as f:
        for raw in f:
            if not raw.endswith(b"\n"):
                break
            try:
                rows.append(model.model_validate_json(raw))
            except ValueError:
                break
            good_bytes += len(raw)
    if good_bytes != path.stat().st_size:
        with path.open("r+b") as f:
            f.truncate(good_bytes)
    return rows


def _append(path: Path, row: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(row.model_dump_json() + "\n")
        f.flush()


def _error(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:500]


def failed_draft(question: Question, cfg: Config, ctx: RunContext, e: Exception, t: float) -> Draft:
    return Draft(
        question_id=question.question_id,
        retrieval_arm=cfg.retrieval.arm,
        answer_text="",
        claims=[],
        evidence={},
        trace_id=ctx.trace_id,
        latency_s=t,
        tokens_in=0,
        tokens_out=0,
        error=_error(e),
    )


def failed_verification(draft: Draft, cfg: Config, e: Exception, t: float) -> VerifiedResult:
    return VerifiedResult(
        question_id=draft.question_id,
        retrieval_arm=draft.retrieval_arm,
        verification_arm=cfg.verification.arm,
        claims_before=draft.claims,
        claims_after=draft.claims,
        verdicts=[],
        revisions_used=0,
        flagged_claim_ids=[],
        latency_s=t,
        tokens_in=0,
        tokens_out=0,
        error=_error(e),
    )


def run_draft(
    cfg: Config,
    questions: Iterable[Question],
    generator: Generator,
    run_dir: Path,
    meta: dict[str, Any],
    tracer: Tracer | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Draft]:
    """Draft stage: one Draft per question, appended to drafts.jsonl. Resumes; returns all."""
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "run_meta.json"
    if meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if old["config"] != meta["config"] or old["split"] != meta["split"]:
            raise RunRefused(f"{run_dir.name} exists with a different config or split")
    else:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    tracer = tracer or Tracer()
    run_id = meta["run_id"]
    path = run_dir / "drafts.jsonl"
    drafts = read_jsonl(path, Draft)
    done = {d.question_id for d in drafts}
    for q in questions:
        if q.question_id in done:
            continue
        ctx = RunContext(
            run_id=run_id,
            thread_id=f"{run_id}:{q.question_id}",
            trace_id=trace_id_for(run_id, q.question_id),
        )
        start = clock()
        with tracer.question(run_id, q.question_id):
            try:
                draft = generator(q, cfg, ctx)
            except Exception as e:  # recorded and scored incorrect, never dropped
                draft = failed_draft(q, cfg, ctx, e, clock() - start)
        _append(path, draft)
        drafts.append(draft)
        done.add(q.question_id)
    tracer.flush()
    return drafts


def run_verify(
    cfg: Config,
    run_dir: Path,
    verifier: Verifier,
    clock: Callable[[], float] = time.monotonic,
) -> list[VerifiedResult]:
    """Verify stage over a run's saved drafts → verified_{arm}.jsonl. Resumes; returns all."""
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    if meta["config"]["retrieval"] != cfg.retrieval.model_dump():
        raise RunRefused("verify config's retrieval section differs from the run's drafts")
    drafts = read_jsonl(run_dir / "drafts.jsonl", Draft)
    path = run_dir / f"verified_{cfg.verification.arm}.jsonl"
    results = read_jsonl(path, VerifiedResult)
    done = {r.question_id for r in results}
    for draft in drafts:
        if draft.question_id in done:
            continue
        start = clock()
        try:
            result = verifier(draft, cfg)
        except Exception as e:  # recorded and counted separately, never dropped
            result = failed_verification(draft, cfg, e, clock() - start)
        _append(path, result)
        results.append(result)
        done.add(draft.question_id)
    return results


def draft_command(
    config_path: str,
    split: str | None = None,
    limit: int | None = None,
    runs_dir: Path = RUNS_DIR,
    splits_path: Path = SPLITS_PATH,
    financebench_path: Path = financebench.DEFAULT_PATH,
    git: GitState | None = None,
    generator: Generator | None = None,
) -> int:
    """`finqa draft`: run the config's generator over a split. Returns a process exit code."""
    cfg = load_config(config_path)
    split = split or cfg.data.question_split
    git = git or git_state()
    check_split_allowed(split, git)
    if limit is not None and split == "test":
        raise RunRefused("--limit is for development on dev only")
    generator = generator or resolve(GENERATORS, cfg.retrieval.arm)
    questions = load_questions(split, splits_path, financebench_path)[:limit]
    run_id = make_run_id(cfg.name, git)
    drafts = run_draft(
        cfg, questions, generator, runs_dir / run_id, run_meta(cfg, split, git, run_id)
    )
    failed = sum(d.error is not None for d in drafts)
    print(f"{run_id}: {len(drafts)} drafts ({failed} failed) → {runs_dir / run_id}")
    return 0


def verify_command(
    run_id: str,
    config_path: str,
    runs_dir: Path = RUNS_DIR,
    git: GitState | None = None,
    verifier: Verifier | None = None,
) -> int:
    """`finqa verify`: run the config's verifier over a run's saved drafts."""
    cfg = load_config(config_path)
    run_dir = runs_dir / run_id
    if not (run_dir / "run_meta.json").exists():
        raise RunRefused(f"no run {run_id} in {runs_dir}")
    split = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))["split"]
    check_split_allowed(split, git or git_state())
    verifier = verifier or resolve(VERIFIERS, cfg.verification.arm)
    results = run_verify(cfg, run_dir, verifier)
    failed = sum(r.error is not None for r in results)
    arm = cfg.verification.arm
    print(f"{run_id}: {len(results)} verified with {arm} ({failed} failed)")
    return 0
