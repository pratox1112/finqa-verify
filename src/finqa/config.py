"""Experiment configuration: configs/base.yaml merged with one override file.

Every setting that differs between runs lives in configs/ (ROADMAP rule 6). Override files
(e.g. configs/grid/r0_v1.yaml) contain only the fields that define them; anything else comes
from base.yaml. Unknown keys are errors, so a typo can't silently fall back to a default.

Secrets come from the environment / .env via `Secrets`, never from configs.

Validate every config:  uv run python -m finqa.config
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"
BASE_CONFIG = CONFIGS_DIR / "base.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelConfig(_Section):
    id: str
    temperature: float = Field(ge=0)
    thinking: str  # one fixed setting for every run, recorded in every log
    max_tokens: int = Field(gt=0)


class LLMConfig(_Section):
    """Call mechanics (not part of the frozen model settings)."""

    max_retries: int = Field(ge=0)  # on HTTP 429 / 5xx, exponential backoff
    requests_per_minute: int | None = Field(default=None, gt=0)  # None = no client-side limit
    tokens_per_minute: int | None = Field(default=None, gt=0)
    cache_dir: str  # on-disk response cache, relative to the repo root


class RetrievalConfig(_Section):
    arm: Literal["closed_book", "rag", "agentic"]
    calculator: bool
    top_k: int = Field(gt=0)
    max_agent_steps: int = Field(gt=0)


class VerificationConfig(_Section):
    arm: Literal["none", "self_check", "grounded"]
    max_revisions: int = Field(ge=0)
    tolerance: float = Field(ge=0)  # relative, e.g. 0.01 = 1%


class EmbeddingConfig(_Section):
    model: str


class DataConfig(_Section):
    question_split: Literal["dev", "test"]


class Config(_Section):
    name: str  # config file stem, used in run IDs (ROADMAP T13)
    model: ModelConfig
    llm: LLMConfig
    retrieval: RetrievalConfig
    verification: VerificationConfig
    embedding: EmbeddingConfig
    data: DataConfig


class Secrets(BaseSettings):
    """API keys and identity, read from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: SecretStr | None = None
    edgar_identity: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into a copy of `base`; override wins on conflicts."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_config(path: str | Path, base: str | Path = BASE_CONFIG) -> Config:
    """Load `path` merged over `base`. Loading the base file itself returns it unmerged."""
    path, base = Path(path), Path(base)
    data = _read_yaml(base)
    if path.resolve() != base.resolve():
        data = deep_merge(data, _read_yaml(path))
    return Config(name=path.stem, **data)


def validate_all(configs_dir: Path = CONFIGS_DIR) -> dict[Path, str]:
    """Load every YAML under `configs_dir`; return {path: error} for those that fail."""
    errors: dict[Path, str] = {}
    base = configs_dir / "base.yaml"
    for path in sorted(configs_dir.rglob("*.yaml")):
        try:
            load_config(path, base)
        except (ValidationError, ValueError, yaml.YAMLError) as e:
            errors[path] = str(e)
    return errors


def main() -> int:
    errors = validate_all()
    for path, error in errors.items():
        print(f"{path.relative_to(CONFIGS_DIR.parent)}:\n{error}\n")
    if errors:
        return 1
    print(f"All configs in {CONFIGS_DIR.name}/ are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
