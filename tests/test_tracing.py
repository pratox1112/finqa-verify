"""Tracing tests. Spans go to an in-memory exporter; any HTTP request fails the test."""

import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from finqa.config import Secrets, load_config
from finqa.llm import LLM
from finqa.tracing import Tracer, trace_id_for

ROOT = Path(__file__).resolve().parents[1]


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network call to {request.url}")


@pytest.fixture(scope="module")
def _client_and_exporter() -> Iterator[tuple[Langfuse, InMemorySpanExporter]]:
    # Langfuse keeps one client per public key per process, so build it once per module.
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://localhost:1",
        span_exporter=exporter,
        httpx_client=httpx.Client(transport=httpx.MockTransport(_no_network)),
    )
    yield client, exporter
    client.shutdown()


@pytest.fixture
def exporter(_client_and_exporter) -> InMemorySpanExporter:
    client, exporter = _client_and_exporter
    client.flush()
    exporter.clear()
    return exporter


@pytest.fixture
def tracer(_client_and_exporter, exporter) -> Tracer:
    return Tracer(client=_client_and_exporter[0])


def spans(tracer: Tracer, exporter: InMemorySpanExporter) -> dict[str, dict]:
    tracer.flush()
    return {
        s.name: {"trace_id": format(s.context.trace_id, "032x"), **dict(s.attributes or {})}
        for s in exporter.get_finished_spans()
    }


# Disabled (no keys): the default for every unit test and for anyone without Langfuse.


def test_disabled_without_keys() -> None:
    tracer = Tracer(Secrets(_env_file=None))
    assert not tracer.enabled
    assert tracer.llm_callbacks() == []
    with tracer.question("run-1", "q-1") as trace_id:
        assert trace_id == trace_id_for("run-1", "q-1")
        with tracer.tool("search_filings", {"q": "x"}) as span:
            assert span is None
    tracer.flush()  # no-op


def test_llm_works_with_tracing_disabled(tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "base.yaml")
    llm = LLM(cfg, FakeListChatModel(responses=["42"]), cache_dir=tmp_path)
    assert not llm.tracer.enabled
    assert llm.invoke([HumanMessage("hi")], run_id="r", question_id="q").content == "42"


def test_trace_id_is_deterministic() -> None:
    a = trace_id_for("2026-11-10_r0_v0_a1b2c3d", "financebench_id_00001")
    assert a == trace_id_for("2026-11-10_r0_v0_a1b2c3d", "financebench_id_00001")
    assert re.fullmatch(r"[0-9a-f]{32}", a)
    assert a != trace_id_for("2026-11-10_r0_v0_a1b2c3d", "financebench_id_00002")
    assert a != trace_id_for("2026-11-10_r1_v0_a1b2c3d", "financebench_id_00001")


# Enabled: everything for one question lands in one trace tagged with run_id and question_id.


def test_question_trace_carries_both_tags(tracer, exporter) -> None:
    with tracer.question("run-1", "q-7") as trace_id:
        with tracer.tool("search_filings", {"query": "revenue"}) as span:
            span.update(output=["chunk-1"])
    recorded = spans(tracer, exporter)
    assert set(recorded) == {"question q-7", "search_filings"}
    for attrs in recorded.values():
        assert attrs["trace_id"] == trace_id
        assert attrs["langfuse.trace.tags"] == ("run:run-1", "question:q-7")
        assert attrs["session.id"] == "run-1"
    assert recorded["search_filings"]["langfuse.observation.type"] == "tool"


def test_llm_call_recorded_in_question_trace(tracer, exporter, tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "base.yaml")
    llm = LLM(cfg, FakeListChatModel(responses=["42"]), cache_dir=tmp_path, tracer=tracer)
    llm.invoke([HumanMessage("hi")], run_id="run-1", question_id="q-7")
    recorded = spans(tracer, exporter)
    generation = next(
        a for a in recorded.values() if a["langfuse.observation.type"] == "generation"
    )
    assert generation["trace_id"] == trace_id_for("run-1", "q-7")
    assert generation["langfuse.trace.tags"] == ("run:run-1", "question:q-7")


def test_nested_question_joins_existing_trace(tracer, exporter, tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "base.yaml")
    llm = LLM(cfg, FakeListChatModel(responses=["a", "b"]), cache_dir=tmp_path, tracer=tracer)
    with tracer.question("run-1", "q-7"):
        llm.invoke([HumanMessage("one")], run_id="run-1", question_id="q-7")
        llm.invoke([HumanMessage("two")], run_id="run-1", question_id="q-7")
    tracer.flush()
    question_spans = [s for s in exporter.get_finished_spans() if s.name == "question q-7"]
    assert len(question_spans) == 1  # inner calls joined the open trace


def test_cache_hits_are_not_traced(tracer, exporter, tmp_path: Path) -> None:
    cfg = load_config(ROOT / "configs" / "base.yaml")
    llm = LLM(cfg, FakeListChatModel(responses=["42"]), cache_dir=tmp_path, tracer=tracer)
    llm.invoke([HumanMessage("hi")], run_id="run-1", question_id="q-7")
    tracer.flush()
    before = len(exporter.get_finished_spans())
    llm.invoke([HumanMessage("hi")], run_id="run-1", question_id="q-7")
    tracer.flush()
    assert len(exporter.get_finished_spans()) == before
