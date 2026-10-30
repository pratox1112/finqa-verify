from pathlib import Path

import pytest
from pydantic import ValidationError

from finqa.config import CONFIGS_DIR, Secrets, deep_merge, load_config, validate_all

GRID = {
    "r0_v0": ("rag", "none", False),
    "r0_v1": ("rag", "self_check", False),
    "r0_v2": ("rag", "grounded", False),
    "r1_v0": ("agentic", "none", True),
    "r1_v1": ("agentic", "self_check", True),
    "r1_v2": ("agentic", "grounded", True),
}


@pytest.mark.parametrize("name", GRID)
def test_grid_config_arms(name: str) -> None:
    retrieval_arm, verification_arm, calculator = GRID[name]
    cfg = load_config(CONFIGS_DIR / "grid" / f"{name}.yaml")
    assert cfg.name == name
    assert cfg.retrieval.arm == retrieval_arm
    assert cfg.verification.arm == verification_arm
    assert cfg.retrieval.calculator is calculator


def test_grid_is_complete() -> None:
    assert {p.stem for p in (CONFIGS_DIR / "grid").glob("*.yaml")} == set(GRID)


def test_grid_configs_share_everything_but_their_arms() -> None:
    base = load_config(CONFIGS_DIR / "base.yaml")
    for name in GRID:
        cfg = load_config(CONFIGS_DIR / "grid" / f"{name}.yaml")
        assert cfg.model == base.model
        assert cfg.embedding == base.embedding
        assert cfg.retrieval.top_k == base.retrieval.top_k
        assert cfg.verification.tolerance == base.verification.tolerance


def test_all_real_configs_valid() -> None:
    assert validate_all() == {}


def test_deep_merge_keeps_unoverridden_keys() -> None:
    base = {"retrieval": {"arm": "rag", "top_k": 5}, "data": {"question_split": "dev"}}
    merged = deep_merge(base, {"retrieval": {"arm": "agentic"}})
    assert merged == {
        "retrieval": {"arm": "agentic", "top_k": 5},
        "data": {"question_split": "dev"},
    }
    assert base["retrieval"]["arm"] == "rag"  # input not mutated


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    override = write(tmp_path, "typo.yaml", "retrieval:\n  topk: 3\n")
    with pytest.raises(ValidationError):
        load_config(override)


def test_invalid_arm_is_rejected(tmp_path: Path) -> None:
    override = write(tmp_path, "bad.yaml", "verification:\n  arm: magic\n")
    with pytest.raises(ValidationError):
        load_config(override)


def test_validate_all_reports_bad_files(tmp_path: Path) -> None:
    (tmp_path / "grid").mkdir()
    write(tmp_path, "base.yaml", (CONFIGS_DIR / "base.yaml").read_text(encoding="utf-8"))
    write(tmp_path / "grid", "good.yaml", "retrieval:\n  arm: agentic\n")
    bad = write(tmp_path / "grid", "bad.yaml", "retrieval:\n  arm: [\n")
    assert list(validate_all(tmp_path)) == [bad]


def test_secrets_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("EDGAR_IDENTITY", "Test User test@example.com")
    secrets = Secrets(_env_file=None)
    assert secrets.groq_api_key is not None
    assert secrets.groq_api_key.get_secret_value() == "test-key"
    assert "test-key" not in repr(secrets)  # never printed
    assert secrets.edgar_identity == "Test User test@example.com"
