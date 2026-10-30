"""The single entry point for every LLM call (ROADMAP rule 7).

`LLM.invoke` adds, around one chat-model call:
  1. an on-disk response cache keyed by (model ID, thinking, temperature, max tokens,
     messages, tools, tool choice), so reruns are free and exactly reproducible;
  2. a client-side requests/tokens-per-minute limiter (Groq limits are per organization);
  3. retries with exponential backoff on HTTP 429 and 5xx;
  4. a log line per call with the thinking setting and token usage;
  5. Langfuse tracing (when keys are set): real calls with a run_id and question_id are
     recorded in that question's trace. Cache hits are logged but not traced.

`LLM.structured` asks for output matching a Pydantic schema via a forced tool call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, messages_from_dict, messages_to_dict
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from finqa.config import CONFIGS_DIR, Config, Secrets
from finqa.tracing import Tracer

logger = logging.getLogger(__name__)

REPO_ROOT = CONFIGS_DIR.parent

# How each `model.thinking` setting is passed to Groq. Confirmed for qwen/qwen3.8-27b from
# Groq's model page on 2026-10-30: "none" = instruct (non-thinking) mode (docs/DECISIONS.md).
THINKING_PARAMS: dict[str, dict[str, Any]] = {
    "off": {"reasoning_effort": "none"},
    "on": {"reasoning_effort": "default"},
}

Schema = TypeVar("Schema", bound=BaseModel)


class StructuredOutputError(ValueError):
    """The model did not return a tool call for the requested schema."""


def is_retryable(exc: BaseException) -> bool:
    """HTTP 429 (rate limited) or any 5xx (server error)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _message_key(message: BaseMessage) -> dict[str, Any]:
    """The parts of a message that affect the model's output (not its random `id`)."""
    key: dict[str, Any] = {"type": message.type, "content": message.content}
    if isinstance(message, AIMessage) and message.tool_calls:
        key["tool_calls"] = [
            {"name": c["name"], "args": c["args"], "id": c.get("id")} for c in message.tool_calls
        ]
    for attr in ("tool_call_id", "name"):
        if getattr(message, attr, None):
            key[attr] = getattr(message, attr)
    return key


def cache_key(
    *,
    model_id: str,
    thinking: str,
    temperature: float,
    max_tokens: int,
    messages: Sequence[BaseMessage],
    tools: Sequence[Any] | None = None,
    tool_choice: str | None = None,
) -> str:
    payload = {
        "model_id": model_id,
        "thinking": thinking,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [_message_key(m) for m in messages],
        "tools": [convert_to_openai_tool(t) for t in tools or []],
        "tool_choice": tool_choice,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    """One JSON file per response under `root/<first 2 hex chars>/<key>.json`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> AIMessage | None:
        path = self._path(key)
        if not path.exists():
            return None
        message = messages_from_dict(json.loads(path.read_text(encoding="utf-8")))[0]
        return message if isinstance(message, AIMessage) else None

    def put(self, key: str, message: AIMessage) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(messages_to_dict([message])), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written entry


class RateLimiter:
    """Sliding 60-second window over requests and tokens.

    A call's token count is only known afterwards, so `acquire` checks an estimate and
    `record` stores the actual count.
    """

    WINDOW_S = 60.0

    def __init__(
        self,
        requests_per_minute: int | None,
        tokens_per_minute: int | None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()  # (time, tokens)

    def acquire(self, estimated_tokens: int) -> None:
        while True:
            now = self._clock()
            while self._events and now - self._events[0][0] >= self.WINDOW_S:
                self._events.popleft()
            requests_ok = self.rpm is None or len(self._events) < self.rpm
            used = sum(tokens for _, tokens in self._events)
            # An empty window always admits one call, so an oversized call can't deadlock.
            tokens_ok = self.tpm is None or not self._events or used + estimated_tokens <= self.tpm
            if requests_ok and tokens_ok:
                return
            self._sleep(max(self.WINDOW_S - (now - self._events[0][0]), 0.01))

    def record(self, tokens: int) -> None:
        self._events.append((self._clock(), tokens))


def _estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    return sum(len(str(m.content)) for m in messages) // 4  # ~4 characters per token


def _usage(message: AIMessage) -> tuple[int, int]:
    usage = message.usage_metadata
    if usage is None:
        return 0, 0
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


class LLM:
    def __init__(
        self,
        cfg: Config,
        chat_model: Any = None,
        *,
        cache_dir: Path | None = None,
        tracer: Tracer | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if cfg.model.thinking not in THINKING_PARAMS:
            raise ValueError(f"unknown thinking setting {cfg.model.thinking!r}")
        self.cfg = cfg
        self.tracer = tracer if tracer is not None else Tracer()
        self._model = chat_model if chat_model is not None else self._build_model()
        self.cache = ResponseCache(cache_dir or REPO_ROOT / cfg.llm.cache_dir)
        self.limiter = RateLimiter(
            cfg.llm.requests_per_minute, cfg.llm.tokens_per_minute, clock=clock, sleep=sleep
        )
        self._clock = clock
        self._retrying = Retrying(
            retry=retry_if_exception(is_retryable),
            stop=stop_after_attempt(cfg.llm.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=60),
            sleep=sleep,
            before_sleep=self._log_retry,
            reraise=True,
        )
        self.usage: dict[str, int] = {"calls": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0}

    def _build_model(self) -> Any:
        from langchain.chat_models import init_chat_model

        m = self.cfg.model
        secrets = Secrets()
        kwargs: dict[str, Any] = {
            "temperature": m.temperature,
            "max_tokens": m.max_tokens,
            "max_retries": 0,  # retries happen here, so they are logged and rate-limited
            **THINKING_PARAMS[m.thinking],
        }
        if secrets.groq_api_key:
            kwargs["api_key"] = secrets.groq_api_key.get_secret_value()
        return init_chat_model(m.id, **kwargs)

    def invoke(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any] | None = None,
        tool_choice: str | None = None,
        *,
        run_id: str | None = None,
        question_id: str | None = None,
    ) -> AIMessage:
        m = self.cfg.model
        key = cache_key(
            model_id=m.id,
            thinking=m.thinking,
            temperature=m.temperature,
            max_tokens=m.max_tokens,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        cached = self.cache.get(key)
        if cached is not None:
            self.usage["cache_hits"] += 1
            self._log(cached, cached=True, latency_s=0.0, run_id=run_id, question_id=question_id)
            return cached

        model = self._model.bind_tools(tools, tool_choice=tool_choice) if tools else self._model
        estimate = _estimate_tokens(messages) + m.max_tokens
        callbacks = self.tracer.llm_callbacks() if run_id and question_id else []

        def attempt() -> AIMessage:
            self.limiter.acquire(estimate)
            try:
                if callbacks:
                    response = model.invoke(list(messages), config={"callbacks": callbacks})
                else:
                    response = model.invoke(list(messages))
            except Exception:
                self.limiter.record(0)  # a failed request still counts against RPM
                raise
            self.limiter.record(sum(_usage(response)))
            return response

        start = self._clock()
        if callbacks:
            assert run_id is not None and question_id is not None
            with self.tracer.question(run_id, question_id):
                response = self._retrying(attempt)
        else:
            response = self._retrying(attempt)
        if not isinstance(response, AIMessage):
            raise TypeError(f"chat model returned {type(response).__name__}, not AIMessage")
        latency_s = self._clock() - start

        self.cache.put(key, response)
        tokens_in, tokens_out = _usage(response)
        self.usage["calls"] += 1
        self.usage["tokens_in"] += tokens_in
        self.usage["tokens_out"] += tokens_out
        self._log(
            response, cached=False, latency_s=latency_s, run_id=run_id, question_id=question_id
        )
        return response

    def structured(
        self,
        messages: Sequence[BaseMessage],
        schema: type[Schema],
        **kwargs: Any,
    ) -> Schema:
        """Force a tool call named after `schema` and validate its arguments.

        Raises StructuredOutputError if no tool call comes back, or pydantic.ValidationError
        if the arguments don't match (the pilot counts both as invalid output).
        """
        response = self.invoke(messages, tools=[schema], tool_choice=schema.__name__, **kwargs)
        if not response.tool_calls:
            raise StructuredOutputError(f"no {schema.__name__} tool call in response")
        return schema.model_validate(response.tool_calls[0]["args"])

    def _log(
        self,
        response: AIMessage,
        *,
        cached: bool,
        latency_s: float,
        run_id: str | None,
        question_id: str | None,
    ) -> None:
        tokens_in, tokens_out = _usage(response)
        logger.info(
            "llm model=%s thinking=%s cached=%s tokens_in=%d tokens_out=%d latency_s=%.2f "
            "run_id=%s question_id=%s",
            self.cfg.model.id,
            self.cfg.model.thinking,
            cached,
            tokens_in,
            tokens_out,
            latency_s,
            run_id,
            question_id,
        )

    def _log_retry(self, state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        logger.warning(
            "llm retry attempt=%d after %s: %s",
            state.attempt_number,
            type(exc).__name__,
            exc,
        )
