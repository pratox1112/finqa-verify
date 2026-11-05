"""What the generators share: the model's answer form, prompt files, and turning one
structured call into a Draft (guide §3.0, §3.2).

The model fills in an `Answer` (answer text, claims, the answering claim); the generator
adds what only it knows (question ID, arm, evidence, trace ID, latency, tokens) to make the
Draft. Every arm uses the same Answer, so drafts compare claim by claim.

A generation that fails (no tool call, output that doesn't validate, a request Groq
refuses) still yields a Draft, with `error` set: it is scored incorrect, never dropped.
Rate limits and server errors that outlast the retries are raised instead, so the run
stops and can be resumed from the cache.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from string import Template

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from finqa.llm import LLM, StructuredOutputError, is_retryable
from finqa.schemas import Chunk, Claim, Draft

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class Answer(BaseModel):
    """Your answer to the question and every number it relies on."""

    answer_text: str
    claims: list[Claim]
    answer_claim_id: str | None = None


def load_prompt(name: str) -> str:
    """A prompt file in src/finqa/prompts/, exactly as written."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def messages(system: str, user: str, **fields: str) -> list[BaseMessage]:
    """The system prompt as written, and the user template with its `$name` fields filled
    (the system prompts contain dollar amounts, so only user templates are templates)."""
    return [
        SystemMessage(load_prompt(system)),
        HumanMessage(Template(load_prompt(user)).substitute(fields)),
    ]


@dataclass
class Call:
    answer: Answer | None
    error: str | None
    tokens_in: int
    tokens_out: int


def answer(llm: LLM, prompt: list[BaseMessage], run_id: str, question_id: str) -> Call:
    """One forced `Answer` tool call (the mechanism of LLM.structured, keeping the token
    counts, which a cached response also carries)."""
    try:
        response = llm.invoke(
            prompt, tools=[Answer], tool_choice="Answer", run_id=run_id, question_id=question_id
        )
    except Exception as e:  # a request Groq refuses, e.g. tool_use_failed or too large
        if is_retryable(e) or getattr(e, "status_code", None) is None:
            raise
        return Call(None, f"{type(e).__name__}: {e}", 0, 0)
    usage = response.usage_metadata
    tokens = (usage["input_tokens"], usage["output_tokens"]) if usage else (0, 0)
    try:
        if not response.tool_calls:
            raise StructuredOutputError("no Answer tool call in response")
        return Call(Answer.model_validate(response.tool_calls[0]["args"]), None, *tokens)
    except (StructuredOutputError, ValidationError) as e:
        return Call(None, f"{type(e).__name__}: {e}", *tokens)


def draft(
    *,
    question_id: str,
    arm: str,
    call: Call,
    evidence: dict[str, Chunk],
    trace_id: str,
    started: float,
) -> Draft:
    a = call.answer
    return Draft(
        question_id=question_id,
        retrieval_arm=arm,
        answer_text=a.answer_text if a else "",
        claims=a.claims if a else [],
        answer_claim_id=a.answer_claim_id if a else None,
        evidence=evidence,
        trace_id=trace_id,
        latency_s=round(time.monotonic() - started, 3),
        tokens_in=call.tokens_in,
        tokens_out=call.tokens_out,
        error=call.error,
    )
