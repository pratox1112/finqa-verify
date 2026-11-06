"""What the generators share: the model's answer form, prompt files, and turning one
structured call into a Draft (guide §3.0, §3.2).

The model fills in an `Answer` (answer text, claims, the answering claim); the generator
adds what only it knows (question ID, arm, evidence, trace ID, latency, tokens) to make the
Draft. Every arm uses the same Answer, so drafts compare claim by claim.

A generation that fails (no tool call, output that doesn't validate, a request Groq
refuses) still yields a Draft, with `error` set: it is scored incorrect, never dropped. When
Groq's tool parser refuses a valid answer (`tool_use_failed`), the answer is read back from
the error and validated like any other (`recover_failed_generation`).
Rate limits and server errors that outlast the retries are raised instead, so the run
stops and can be resumed from the cache.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from string import Template

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from finqa.llm import LLM, StructuredOutputError, is_retryable
from finqa.schemas import Chunk, Claim, Draft

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class Answer(BaseModel):
    """Your answer to the question and every number it relies on."""

    answer_text: str
    claims: list[Claim]
    answer_claim_id: str | None = Field(
        default=None,
        description='claim_id of the claim that answers the question, e.g. "c3"; null only if '
        "the answer is not a single number",
    )


def answer_claim_id(a: Answer) -> str | None:
    """The answering claim's ID, tolerating the model's slips: "3" means "c3", "null" means
    unset, and an unset or unknown ID with claims present means the last claim (the prompts
    put the answer after its inputs). Scoring reads it only when the gold answer is a number
    (finqa.eval.scoring), so a qualitative answer is unaffected."""
    ids = [c.claim_id for c in a.claims]
    raw = (a.answer_claim_id or "").strip()
    if raw in ids:
        return raw
    if raw.isdigit() and f"c{raw}" in ids:
        return f"c{raw}"
    return ids[-1] if ids else None


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


_PARAMETER = re.compile(r"<parameter=(\w+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def recover_failed_generation(error: Exception) -> Answer | None:
    """The model's Answer from a Groq `tool_use_failed` error, or None.

    Groq refuses some well-formed answers because its tool-call parser trips (the model names
    the tool "Call" instead of "Answer", or a long claims list), and returns the model's text
    as `failed_generation`: `<function=...><parameter=answer_text>...</parameter>...`. The
    parameters are read back and validated exactly like a normal call, so anything that is
    not a valid Answer still fails. Token counts are unknown for these calls (recorded as 0).
    """
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict) or body.get("code") != "tool_use_failed":
        return None
    params = dict(_PARAMETER.findall(str(body.get("failed_generation") or "")))
    if "answer_text" not in params or "claims" not in params:
        return None
    try:
        claim_id = params.get("answer_claim_id")
        return Answer.model_validate(
            {
                "answer_text": params["answer_text"],
                "claims": json.loads(params["claims"]),
                "answer_claim_id": None if claim_id in (None, "null", "None", "") else claim_id,
            }
        )
    except (json.JSONDecodeError, ValidationError):
        return None


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
        recovered = recover_failed_generation(e)
        if recovered is not None:
            logger.warning("question %s: Answer recovered from Groq tool_use_failed", question_id)
            return Call(recovered, None, 0, 0)
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
        answer_claim_id=answer_claim_id(a) if a else None,
        evidence=evidence,
        trace_id=trace_id,
        latency_s=round(time.monotonic() - started, 3),
        tokens_in=call.tokens_in,
        tokens_out=call.tokens_out,
        error=call.error,
    )
