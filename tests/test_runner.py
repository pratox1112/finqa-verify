"""Runner acceptance (ROADMAP P2.2): dummy end to end, resume after a kill, T12 guard, T13 IDs."""

import json
from datetime import date
from pathlib import Path

import pytest

from finqa.cli import build_parser
from finqa.config import BASE_CONFIG
from finqa.eval import dummies, runner
from finqa.eval.questions import load_questions
from finqa.schemas import Draft, VerifiedResult

FIXTURE = Path(__file__).parent / "fixtures" / "financebench_sample.jsonl"
CONFIG = str(BASE_CONFIG)
CLEAN_MAIN = runner.GitState(commit="a1b2c3d4e5f6", short="a1b2c3d", branch="main", dirty=False)


@pytest.fixture
def splits(tmp_path: Path) -> Path:
    path = tmp_path / "splits.json"
    path.write_text(
        json.dumps(
            {
                "dev": ["fb_synth_001", "fb_synth_002"],
                "test": ["fb_synth_003"],
                "question_types": {
                    "fb_synth_001": "single_fact",
                    "fb_synth_002": "calculation",
                    "fb_synth_003": "qualitative",
                },
            }
        )
    )
    return path


def draft(tmp_path: Path, splits: Path, **kw):
    kw.setdefault("git", CLEAN_MAIN)
    kw.setdefault("generator", dummies.generate)
    return runner.draft_command(
        CONFIG, runs_dir=tmp_path / "runs", splits_path=splits, financebench_path=FIXTURE, **kw
    )


def only_run(tmp_path: Path) -> Path:
    (run_dir,) = (tmp_path / "runs").iterdir()
    return run_dir


def test_questions_follow_the_split(splits: Path):
    qs = load_questions("dev", splits, FIXTURE)
    assert [q.question_id for q in qs] == ["fb_synth_001", "fb_synth_002"]
    assert qs[1].question_type == "calculation"
    assert qs[0].gold_evidence == ("Revenue 1,200",)


def test_run_id_format():
    assert runner.make_run_id("r0_v0", CLEAN_MAIN, date(2026, 11, 10)) == "2026-11-10_r0_v0_a1b2c3d"


def test_dummy_runs_through_both_stages(tmp_path: Path, splits: Path):
    assert draft(tmp_path, splits, split="dev") == 0
    run_dir = only_run(tmp_path)
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    assert [d.question_id for d in drafts] == ["fb_synth_001", "fb_synth_002"]
    assert drafts[0].claims[0].value == 42.0
    meta = json.loads((run_dir / "run_meta.json").read_text())
    assert meta["git_commit"] == CLEAN_MAIN.commit and meta["split"] == "dev"
    assert meta["model_id"] and meta["thinking"] and meta["package_versions"]["pydantic"]
    assert run_dir.name.endswith("_base_a1b2c3d")

    code = runner.verify_command(
        run_dir.name, CONFIG, runs_dir=tmp_path / "runs", git=CLEAN_MAIN, verifier=dummies.verify
    )
    assert code == 0
    results = runner.read_jsonl(run_dir / "verified_none.jsonl", VerifiedResult)
    assert [r.claims_after for r in results] == [d.claims for d in drafts]


def test_killed_run_resumes(tmp_path: Path, splits: Path):
    calls: list[str] = []

    def dies_on_second(question, cfg, ctx):
        calls.append(question.question_id)
        if len(calls) == 2:
            raise KeyboardInterrupt  # killed mid-run: not an Exception, so not recorded
        return dummies.generate(question, cfg, ctx)

    with pytest.raises(KeyboardInterrupt):
        draft(tmp_path, splits, split="dev", generator=dies_on_second)
    run_dir = only_run(tmp_path)
    with (run_dir / "drafts.jsonl").open("a") as f:
        f.write('{"question_id": "half-writ')  # a line cut off by the kill
    assert len(runner.read_jsonl(run_dir / "drafts.jsonl", Draft)) == 1

    calls.clear()
    draft(tmp_path, splits, split="dev")
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    assert [d.question_id for d in drafts] == ["fb_synth_001", "fb_synth_002"]


def test_rerun_skips_finished_questions(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")
    seen: list[str] = []

    def record(question, cfg, ctx):
        seen.append(question.question_id)
        return dummies.generate(question, cfg, ctx)

    draft(tmp_path, splits, split="dev", generator=record)
    assert seen == []


def test_failed_generation_is_kept_not_dropped(tmp_path: Path, splits: Path):
    def broken(question, cfg, ctx):
        raise ValueError("structured_output_invalid")

    draft(tmp_path, splits, split="dev", generator=broken)
    drafts = runner.read_jsonl(only_run(tmp_path) / "drafts.jsonl", Draft)
    assert len(drafts) == 2 and all("structured_output_invalid" in d.error for d in drafts)


def test_failed_verification_keeps_claims(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")

    def broken(d, cfg):
        raise RuntimeError("api_error: 429")

    runner.verify_command(
        only_run(tmp_path).name, CONFIG, runs_dir=tmp_path / "runs", git=CLEAN_MAIN, verifier=broken
    )
    (result, _) = runner.read_jsonl(only_run(tmp_path) / "verified_none.jsonl", VerifiedResult)
    assert result.error and result.claims_after == result.claims_before


@pytest.mark.parametrize(
    "git",
    [
        runner.GitState("a" * 40, "aaaaaaa", "main", dirty=True),
        runner.GitState("a" * 40, "aaaaaaa", "dheepak/runner", dirty=False),
    ],
)
def test_test_split_refused_off_clean_main(tmp_path: Path, splits: Path, git):
    with pytest.raises(runner.RunRefused):
        draft(tmp_path, splits, split="test", git=git)
    assert not (tmp_path / "runs").exists()


def test_test_split_allowed_on_clean_main(tmp_path: Path, splits: Path):
    assert draft(tmp_path, splits, split="test") == 0


def test_limit_only_on_dev(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev", limit=1)
    assert len(runner.read_jsonl(only_run(tmp_path) / "drafts.jsonl", Draft)) == 1
    with pytest.raises(runner.RunRefused):
        draft(tmp_path, splits, split="test", limit=1)


def test_resume_with_other_config_refused(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")
    meta_path = only_run(tmp_path) / "run_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["config"]["retrieval"]["top_k"] = 99
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(runner.RunRefused):
        draft(tmp_path, splits, split="dev")


def test_verify_with_other_retrieval_refused(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")
    other = tmp_path / "agentic.yaml"
    other.write_text('retrieval:\n  arm: "agentic"\n  calculator: true\n')
    with pytest.raises(runner.RunRefused, match="retrieval"):
        runner.verify_command(
            only_run(tmp_path).name,
            str(other),
            runs_dir=tmp_path / "runs",
            git=CLEAN_MAIN,
            verifier=dummies.verify,
        )


def test_unbuilt_arm_is_reported(tmp_path: Path, splits: Path):
    with pytest.raises(runner.RunRefused, match="not built yet"):
        draft(tmp_path, splits, split="dev", generator=None)


def test_cli_arguments():
    args = build_parser().parse_args(["draft", "--config", "c.yaml", "--split", "dev"])
    assert (args.command, args.config, args.split, args.limit) == ("draft", "c.yaml", "dev", None)
    assert build_parser().parse_args(["verify", "--run", "r", "--config", "c.yaml"]).run == "r"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["draft", "--config", "c.yaml", "--split", "train"])


def test_cli_turns_refusal_into_exit_code(monkeypatch: pytest.MonkeyPatch):
    from finqa import cli

    def refuse(*a, **k):
        raise runner.RunRefused("nope")

    monkeypatch.setattr(runner, "draft_command", refuse)
    assert cli.main(["draft", "--config", "c.yaml"]) == 2
