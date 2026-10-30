"""LLM wrapper tests with a fake chat model. No network."""

from pathlib import Path
from typing import Any

import groq
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from finqa.config import Config, load_config
from finqa.llm import LLM, RateLimiter, StructuredOutputError, cache_key

QUESTION = [SystemMessage("Answer briefly."), HumanMessage("What was revenue in FY2022?")]


def reply(content: str = "42", **kwargs: Any) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        **kwargs,
    )


def http_error(status: int) -> groq.APIStatusError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com"))
    cls = {429: groq.RateLimitError, 500: groq.InternalServerError}.get(
        status, groq.BadRequestError
    )
    return cls(f"HTTP {status}", response=response, body=None)


class FakeChat:
    """Returns (or raises) the given items in order and records how it was called."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)
        self.calls = 0
        self.bound: tuple[Any, Any] | None = None

    def bind_tools(self, tools: Any, tool_choice: Any = None) -> "FakeChat":
        self.bound = (tools, tool_choice)
        return self

    def invoke(self, messages: Any) -> Any:
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def cfg() -> Config:
    return load_config(Path(__file__).resolve().parents[1] / "configs" / "base.yaml")


@pytest.fixture
def sleeps() -> list[float]:
    return []


def make_llm(cfg: Config, chat: FakeChat, tmp_path: Path, sleeps: list[float]) -> LLM:
    return LLM(cfg, chat, cache_dir=tmp_path / "cache", sleep=sleeps.append)


# (a) A repeated call hits the cache.


def test_repeated_call_hits_cache(cfg, tmp_path, sleeps) -> None:
    chat = FakeChat(reply("42"))
    llm = make_llm(cfg, chat, tmp_path, sleeps)
    first = llm.invoke(QUESTION)
    second = llm.invoke(QUESTION)
    assert first.content == second.content == "42"
    assert chat.calls == 1
    assert llm.usage == {"calls": 1, "cache_hits": 1, "tokens_in": 10, "tokens_out": 2}


def test_cache_persists_across_instances(cfg, tmp_path, sleeps) -> None:
    make_llm(cfg, FakeChat(reply("42")), tmp_path, sleeps).invoke(QUESTION)
    fresh = FakeChat()  # would fail if called
    assert make_llm(cfg, fresh, tmp_path, sleeps).invoke(QUESTION).content == "42"
    assert fresh.calls == 0


def test_cached_response_keeps_usage_and_tool_calls(cfg, tmp_path, sleeps) -> None:
    call = {"name": "search", "args": {"q": "revenue"}, "id": "call_1"}
    make_llm(cfg, FakeChat(reply("", tool_calls=[call])), tmp_path, sleeps).invoke(QUESTION)
    cached = make_llm(cfg, FakeChat(), tmp_path, sleeps).invoke(QUESTION)
    assert cached.tool_calls[0]["args"] == {"q": "revenue"}
    assert cached.usage_metadata is not None
    assert cached.usage_metadata["input_tokens"] == 10


# (b) A 429 triggers a retry.


def test_429_is_retried(cfg, tmp_path, sleeps) -> None:
    chat = FakeChat(http_error(429), reply("42"))
    assert make_llm(cfg, chat, tmp_path, sleeps).invoke(QUESTION).content == "42"
    assert chat.calls == 2
    assert len(sleeps) == 1  # backed off once


def test_5xx_is_retried(cfg, tmp_path, sleeps) -> None:
    chat = FakeChat(http_error(500), http_error(500), reply("42"))
    make_llm(cfg, chat, tmp_path, sleeps).invoke(QUESTION)
    assert chat.calls == 3
    assert sleeps[1] > sleeps[0]  # exponential


def test_400_is_not_retried(cfg, tmp_path, sleeps) -> None:
    chat = FakeChat(http_error(400), reply("42"))
    with pytest.raises(groq.BadRequestError):
        make_llm(cfg, chat, tmp_path, sleeps).invoke(QUESTION)
    assert chat.calls == 1


def test_gives_up_after_max_retries(cfg, tmp_path, sleeps) -> None:
    attempts = cfg.llm.max_retries + 1
    chat = FakeChat(*[http_error(429)] * attempts)
    with pytest.raises(groq.RateLimitError):
        make_llm(cfg, chat, tmp_path, sleeps).invoke(QUESTION)
    assert chat.calls == attempts


def test_failed_call_is_not_cached(cfg, tmp_path, sleeps) -> None:
    with pytest.raises(groq.BadRequestError):
        make_llm(cfg, FakeChat(http_error(400)), tmp_path, sleeps).invoke(QUESTION)
    chat = FakeChat(reply("42"))
    make_llm(cfg, chat, tmp_path, sleeps).invoke(QUESTION)
    assert chat.calls == 1


# (c) Cache keys differ when any key component differs.


class Answer(BaseModel):
    value: float
    unit: str


KEY_ARGS: dict[str, Any] = {
    "model_id": "groq:qwen/qwen3.8-27b",
    "thinking": "off",
    "temperature": 0.0,
    "max_tokens": 2048,
    "messages": QUESTION,
    "tools": None,
}


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "groq:other-model"},
        {"thinking": "on"},
        {"temperature": 0.7},
        {"max_tokens": 512},
        {"messages": [*QUESTION, HumanMessage("And in FY2023?")]},
        {"messages": [QUESTION[0], HumanMessage("What was revenue in FY2021?")]},
        {"tools": [Answer]},
    ],
    ids=["model_id", "thinking", "temperature", "max_tokens", "extra_message", "content", "tools"],
)
def test_cache_key_changes_with_each_component(change: dict[str, Any]) -> None:
    assert cache_key(**KEY_ARGS) != cache_key(**{**KEY_ARGS, **change})


def test_cache_key_is_stable_and_ignores_message_ids() -> None:
    assert cache_key(**KEY_ARGS) == cache_key(**KEY_ARGS)
    a = [*QUESTION, AIMessage("x", id="run-1")]
    b = [*QUESTION, AIMessage("x", id="run-2")]
    assert cache_key(**{**KEY_ARGS, "messages": a}) == cache_key(**{**KEY_ARGS, "messages": b})


# Structured output, tools, rate limiting, config.


def test_structured_output_parsed(cfg, tmp_path, sleeps) -> None:
    call = {"name": "Answer", "args": {"value": 1.2, "unit": "USD"}, "id": "c1"}
    chat = FakeChat(reply("", tool_calls=[call]))
    answer = make_llm(cfg, chat, tmp_path, sleeps).structured(QUESTION, Answer)
    assert answer == Answer(value=1.2, unit="USD")
    assert chat.bound is not None and chat.bound[1] == "Answer"  # tool call was forced


def test_structured_output_missing_tool_call_raises(cfg, tmp_path, sleeps) -> None:
    with pytest.raises(StructuredOutputError):
        make_llm(cfg, FakeChat(reply("1.2 USD")), tmp_path, sleeps).structured(QUESTION, Answer)


def test_rate_limiter_waits_when_requests_per_minute_reached() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2, None, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.acquire(0)
        limiter.record(0)
    assert sleeps == [60.0]


def test_rate_limiter_waits_when_tokens_per_minute_reached() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(None, 1000, clock=lambda: now[0], sleep=sleep)
    limiter.acquire(800)
    limiter.record(900)
    now[0] = 10.0
    limiter.acquire(200)  # 900 + 200 > 1000: wait until the first call leaves the window
    assert sleeps == [50.0]


def test_unknown_thinking_setting_rejected(cfg, tmp_path) -> None:
    bad = cfg.model_copy(update={"model": cfg.model.model_copy(update={"thinking": "maybe"})})
    with pytest.raises(ValueError, match="thinking"):
        LLM(bad, FakeChat(), cache_dir=tmp_path)
