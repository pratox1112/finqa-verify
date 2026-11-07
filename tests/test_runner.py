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


class FakeAPIError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):  # same class name as groq's / openai's
    pass


@pytest.mark.parametrize(
    "error", [FakeAPIError(429), FakeAPIError(503), APIConnectionError("reset"), TimeoutError()]
)
def test_transient_api_error_stops_the_run_and_resumes(
    tmp_path: Path, splits: Path, error: Exception
):
    calls: list[str] = []

    def rate_limited_on_second(question, cfg, ctx):
        calls.append(question.question_id)
        if len(calls) == 2:
            raise error
        return dummies.generate(question, cfg, ctx)

    with pytest.raises(runner.RunStopped, match="fb_synth_002 after 1 finished"):
        draft(tmp_path, splits, split="dev", generator=rate_limited_on_second)
    run_dir = only_run(tmp_path)
    (first,) = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)  # nothing for question 2
    assert first.error is None

    draft(tmp_path, splits, split="dev")
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    assert [d.question_id for d in drafts] == ["fb_synth_001", "fb_synth_002"]
    assert all(d.error is None for d in drafts)


def test_client_error_is_still_a_failed_draft(tmp_path: Path, splits: Path):
    def too_large(question, cfg, ctx):
        raise FakeAPIError(413)  # a request Groq refuses: about the system, not the network

    draft(tmp_path, splits, split="dev", generator=too_large)
    drafts = runner.read_jsonl(only_run(tmp_path) / "drafts.jsonl", Draft)
    assert len(drafts) == 2 and all("413" in (d.error or "") for d in drafts)


def test_transient_error_in_verify_stops_without_recording(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")

    def rate_limited(d, cfg):
        raise FakeAPIError(429)

    with pytest.raises(runner.RunStopped):
        runner.verify_command(
            only_run(tmp_path).name,
            CONFIG,
            runs_dir=tmp_path / "runs",
            git=CLEAN_MAIN,
            verifier=rate_limited,
        )
    assert not runner.read_jsonl(only_run(tmp_path) / "verified_none.jsonl", VerifiedResult)


class FlushCounter:
    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


def test_stopped_verify_flushes_traces_first(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")

    def rate_limited(d, cfg):
        raise FakeAPIError(429)

    tracer = FlushCounter()
    cfg = runner.load_config(CONFIG)
    with pytest.raises(runner.RunStopped):
        runner.run_verify(cfg, only_run(tmp_path), rate_limited, tracer=tracer)  # type: ignore[arg-type]
    assert tracer.flushes == 1


def test_cli_turns_stop_into_exit_code(monkeypatch: pytest.MonkeyPatch):
    from finqa import cli

    def stop(*a, **k):
        raise runner.RunStopped("rate limited")

    monkeypatch.setattr(runner, "draft_command", stop)
    assert cli.main(["draft", "--config", "c.yaml"]) == 3


def test_failed_verification_keeps_claims(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev")

    def broken(d, cfg):
        raise RuntimeError("verifier_output_invalid")

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


def subset_file(tmp_path: Path, ids: list[str]) -> Path:
    path = tmp_path / "subset.json"
    path.write_text(json.dumps({"ids": ids}))
    return path


def test_subset_runs_only_listed_questions(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev", subset=subset_file(tmp_path, ["fb_synth_002"]))
    run_dir = only_run(tmp_path)
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    assert [d.question_id for d in drafts] == ["fb_synth_002"]
    assert json.loads((run_dir / "run_meta.json").read_text())["subset"] == "subset.json"


def test_subset_allowed_on_test(tmp_path: Path, splits: Path):
    subset = subset_file(tmp_path, ["fb_synth_003"])
    assert draft(tmp_path, splits, split="test", subset=subset) == 0


def test_subset_with_ids_outside_the_split_refused(tmp_path: Path, splits: Path):
    with pytest.raises(runner.RunRefused, match="not in this split"):
        draft(tmp_path, splits, split="test", subset=subset_file(tmp_path, ["fb_synth_001"]))


def test_resume_with_other_subset_refused(tmp_path: Path, splits: Path):
    draft(tmp_path, splits, split="dev", subset=subset_file(tmp_path, ["fb_synth_002"]))
    with pytest.raises(runner.RunRefused, match="subset"):
        draft(tmp_path, splits, split="dev")


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


def test_unbuilt_arm_is_reported(tmp_path: Path, splits: Path, monkeypatch: pytest.MonkeyPatch):
    # Point the config's arm at a module that does not exist, so the test does not
    # depend on which generators are built yet.
    monkeypatch.setitem(runner.GENERATORS, "rag", "finqa.generators.not_built:generate")
    with pytest.raises(runner.RunRefused, match="not built yet"):
        draft(tmp_path, splits, split="dev", generator=None)


def test_cli_arguments():
    args = build_parser().parse_args(["draft", "--config", "c.yaml", "--split", "dev"])
    assert (args.command, args.config, args.split, args.limit) == ("draft", "c.yaml", "dev", None)
    assert build_parser().parse_args(["verify", "--run", "r", "--config", "c.yaml"]).run == "r"
    args = build_parser().parse_args(["draft", "--config", "c.yaml", "--subset", "s.json"])
    assert args.subset == Path("s.json")
    with pytest.raises(SystemExit):
        build_parser().parse_args(["draft", "--config", "c.yaml", "--split", "train"])


def test_cli_turns_refusal_into_exit_code(monkeypatch: pytest.MonkeyPatch):
    from finqa import cli

    def refuse(*a, **k):
        raise runner.RunRefused("nope")

    monkeypatch.setattr(runner, "draft_command", refuse)
    assert cli.main(["draft", "--config", "c.yaml"]) == 2
