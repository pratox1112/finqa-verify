"""Real Groq call traced to real Langfuse (ROADMAP P0.5 manual acceptance check).

Run:  uv run pytest -m integration tests/test_tracing_integration.py -s
Then open the printed trace in Langfuse and confirm the tags run:p0.5-check and
question:tracing-smoke. Skipped unless GROQ_API_KEY and both Langfuse keys are set.
"""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from finqa.config import Secrets, load_config
from finqa.llm import LLM
from finqa.tracing import Tracer

pytestmark = pytest.mark.integration

RUN_ID, QUESTION_ID = "p0.5-check", "tracing-smoke"


def test_real_call_appears_in_langfuse(tmp_path: Path) -> None:
    secrets = Secrets()
    if not (secrets.groq_api_key and secrets.langfuse_public_key and secrets.langfuse_secret_key):
        pytest.skip("needs GROQ_API_KEY, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
    tracer = Tracer(secrets)
    llm = LLM(
        load_config(Path(__file__).resolve().parents[1] / "configs" / "base.yaml"),
        cache_dir=tmp_path,
        tracer=tracer,
    )  # fresh cache: forces a real, traced call
    with tracer.question(RUN_ID, QUESTION_ID) as trace_id:
        llm.invoke(
            [HumanMessage("Reply with the single word: ok")], run_id=RUN_ID, question_id=QUESTION_ID
        )
    tracer.flush()
    print(f"\nLangfuse trace id: {trace_id}  (tags run:{RUN_ID}, question:{QUESTION_ID})")
