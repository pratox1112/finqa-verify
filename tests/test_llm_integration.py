"""One real Groq call. Runs only with `pytest -m integration` and a GROQ_API_KEY."""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from finqa.config import Secrets, load_config
from finqa.llm import LLM

pytestmark = pytest.mark.integration


@pytest.fixture
def llm(tmp_path: Path) -> LLM:
    if Secrets().groq_api_key is None:
        pytest.skip("GROQ_API_KEY not set")
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "base.yaml")
    return LLM(cfg, cache_dir=tmp_path)


def test_real_call_returns_text_and_usage(llm: LLM) -> None:
    response = llm.invoke([HumanMessage("Reply with the single word: ok")])
    assert str(response.content).strip()
    assert llm.usage["tokens_in"] > 0
    assert llm.invoke([HumanMessage("Reply with the single word: ok")]) == response  # cached
