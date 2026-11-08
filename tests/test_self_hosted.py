"""Self-hosted vLLM serving: thinking switch, client, dev-only configs, agreement check.

No network: the vLLM client is only constructed, never called.
"""

import json
from pathlib import Path

import pytest

from finqa.config import CONFIGS_DIR, Secrets, load_config
from finqa.eval import compare, dummies, runner
from finqa.eval.questions import load_questions
from finqa.eval.scoring import Gold, Judgment
from finqa.llm import LLM, build_vllm_model, thinking_params

FIXTURE = Path(__file__).parent / "fixtures" / "financebench_sample.jsonl"
CLEAN_MAIN = runner.GitState(commit="a" * 40, short="aaaaaaa", branch="main", dirty=False)
IDS = ["fb_synth_001", "fb_synth_002", "fb_synth_003"]
GOLD = {
    "fb_synth_001": Gold("fb_synth_001", "42", "number", 42.0, "USD"),  # dummy answers 42
    "fb_synth_002": Gold("fb_synth_002", "Yes, 1.4.", "text_with_numbers", None, ""),
    "fb_synth_003": Gold("fb_synth_003", "$1,200", "number", 1200.0, "USD"),
}
GROQ_OVERRIDE = """model:
  id: "groq:qwen/qwen3.8-27b"
  temperature: 0
  thinking: "off"
  max_tokens: 2048
retrieval:
  arm: "rag"
  calculator: false
"""


@pytest.fixture
def groq_config(tmp_path: Path) -> Path:
    """An override whose model differs from base.yaml (the old Groq serving)."""
    path = tmp_path / "r0_v0_groq.yaml"
    path.write_text(GROQ_OVERRIDE, encoding="utf-8")
    return path


# --- Thinking switch and client --------------------------------------------------------------


def test_thinking_params_per_provider():
    assert thinking_params("groq:qwen/qwen3.8-27b", "off") == {"reasoning_effort": "none"}
    off = thinking_params("vllm:Qwen/Qwen3.8-27B", "off")
    assert off == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


@pytest.mark.parametrize(
    ("model_id", "thinking"),
    [("openai:gpt", "off"), ("vllm:Qwen/Qwen3.8-27B", "maybe"), ("groq:x", "high")],
)
def test_thinking_params_rejects_unknown(model_id: str, thinking: str):
    with pytest.raises(ValueError):
        thinking_params(model_id, thinking)


def test_vllm_client_sends_thinking_off_to_the_configured_server():
    secrets = Secrets(vllm_base_url="http://localhost:8000/v1", vllm_api_key="k", _env_file=None)
    kwargs = {"temperature": 0, "max_tokens": 2048, "max_retries": 0}
    kwargs |= thinking_params("vllm:Qwen/Qwen3.8-27B", "off")
    model = build_vllm_model("vllm:Qwen/Qwen3.8-27B", secrets, kwargs)
    assert model.model_name == "Qwen/Qwen3.8-27B"
    assert model.openai_api_base == "http://localhost:8000/v1"
    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert model.temperature == 0
    assert model.max_tokens == 2048


def test_vllm_client_needs_a_base_url():
    with pytest.raises(ValueError, match="VLLM_BASE_URL"):
        build_vllm_model("vllm:Qwen/Qwen3.8-27B", Secrets(_env_file=None), {})


def test_base_model_is_self_hosted_with_thinking_off(tmp_path: Path):
    cfg = load_config(CONFIGS_DIR / "base.yaml")
    assert cfg.model.id == "vllm:Qwen/Qwen3.8-27B"
    assert (cfg.model.temperature, cfg.model.thinking, cfg.model.max_tokens) == (0, "off", 2048)
    LLM(cfg, chat_model=object(), cache_dir=tmp_path)  # a valid thinking setting for vllm


# --- Dev only --------------------------------------------------------------------------------


@pytest.fixture
def splits(tmp_path: Path) -> Path:
    path = tmp_path / "splits.json"
    types = dict(zip(IDS, ["single_fact", "calculation", "qualitative"], strict=True))
    path.write_text(json.dumps({"dev": IDS, "test": IDS, "question_types": types}))
    return path


def draft(config: Path, split: str, runs: Path, splits: Path) -> int:
    return runner.draft_command(
        str(config),
        split=split,
        runs_dir=runs,
        splits_path=splits,
        financebench_path=FIXTURE,
        git=CLEAN_MAIN,
        generator=dummies.generate,
    )


def test_other_model_refused_on_test_even_from_clean_main(
    groq_config: Path, tmp_path: Path, splits: Path
):
    with pytest.raises(runner.RunRefused, match="frozen model settings"):
        draft(groq_config, "test", tmp_path / "runs", splits)
    assert not (tmp_path / "runs").exists()


def test_base_model_still_allowed_on_test(tmp_path: Path, splits: Path):
    assert draft(CONFIGS_DIR / "baselines/s0_closed_book.yaml", "test", tmp_path, splits) == 0


# --- Agreement check -------------------------------------------------------------------------


def judge_says_no(question, gold_answer, model_answer):
    return Judgment(correct=False, reason="different conclusion")


def run_pair(tmp_path: Path, splits: Path, split: str, other: Path) -> tuple[Path, list[str]]:
    runs = tmp_path / "runs"
    ids = []
    for config in (other, CONFIGS_DIR / "grid/r0_v0.yaml"):
        draft(config, split, runs, splits)
        ids.append(f"{runner.make_run_id(config.stem, CLEAN_MAIN)}")
    return runs, ids


def test_agreement_report_per_question(tmp_path: Path, splits: Path, groq_config: Path):
    runs, (a, b) = run_pair(tmp_path, splits, "dev", groq_config)
    questions = {q.question_id: q for q in load_questions("dev", splits, FIXTURE)}
    assert (
        compare.compare_command(
            a, b, runs, questions, GOLD, make_judge=lambda cfg, run_id: judge_says_no
        )
        == 0
    )
    text = (runs / b / f"agreement_vs_{a}.md").read_text(encoding="utf-8")
    # The same dummy generator on both sides: every question agrees.
    assert "Same outcome: 3/3. Same answer claim (value and unit): 3/3." in text
    assert "| fb_synth_001 | single_fact | correct | correct | 42 USD | 42 USD | yes |" in text
    assert "| 1 | 0 | 0 | 2 |" in text  # McNemar row: both correct, only a, only b, both wrong


def test_agreement_check_is_dev_only(tmp_path: Path, splits: Path):
    runs = tmp_path / "runs"
    draft(CONFIGS_DIR / "grid/r0_v0.yaml", "test", runs, splits)
    test_run = runner.make_run_id("r0_v0", CLEAN_MAIN)
    with pytest.raises(runner.RunRefused, match="dev only"):
        compare.compare_command(test_run, test_run, runs)


def test_agreement_report_flags_disagreement():
    from finqa.eval.tables import Row
    from finqa.schemas import Draft

    def d(qid: str, text: str) -> Draft:
        return Draft(
            question_id=qid,
            retrieval_arm="rag",
            answer_text=text,
            claims=[],
            evidence={},
            trace_id="t",
            latency_s=0.0,
            tokens_in=0,
            tokens_out=0,
        )

    def r(qid: str, outcome: str) -> Row:
        return Row(qid, "qualitative", outcome, "judge", "", 0.0, 0, 0, False)

    text = compare.agreement_report(
        "groq", [d("q1", "Yes")], [r("q1", "correct")], "vllm", [d("q1", "")], [r("q1", "refused")]
    )
    assert "Same outcome: 0/1." in text
    assert "| q1 | qualitative | correct | refused | text | none | NO |" in text
    assert "WARNING" not in text

    failed = d("q1", "").model_copy(update={"error": "OpenAIInvalidRequestError: 400"})
    text = compare.agreement_report(
        "groq", [d("q1", "x")], [r("q1", "incorrect")], "vllm", [failed], [r("q1", "incorrect")]
    )
    assert "WARNING: failed drafts (groq: 0/1, vllm: 1/1)" in text
    assert "| failed | yes |" in text
