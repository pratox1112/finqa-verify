"""Langfuse tracing (ROADMAP P0.5).

One trace per (run, question), tagged with both IDs, so every LLM call and tool call for a
question can be found together. Tracing is OFF unless both LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set; when off, nothing is imported, sent or logged.

    tracer = Tracer()
    with tracer.question(run_id, question_id) as trace_id:   # trace_id -> Draft.trace_id
        llm.invoke(messages, run_id=run_id, question_id=question_id)
        with tracer.tool("search_filings", {"query": q}) as span:
            ...
            if span: span.update(output=result_ids)
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from finqa.config import Secrets

# The (run_id, question_id) whose trace is currently open, so nested calls don't open another.
_current: ContextVar[tuple[str, str] | None] = ContextVar("finqa_trace", default=None)


def trace_id_for(run_id: str, question_id: str) -> str:
    """Deterministic 32-hex trace ID: the same run and question always map to the same trace."""
    return hashlib.sha256(f"{run_id}:{question_id}".encode()).hexdigest()[:32]


class Tracer:
    def __init__(self, secrets: Secrets | None = None, client: Any = None) -> None:
        """`client` is a ready Langfuse client (tests); otherwise one is built from `secrets`."""
        if client is None:
            secrets = secrets or Secrets()
            if secrets.langfuse_public_key and secrets.langfuse_secret_key:
                from langfuse import Langfuse

                client = Langfuse(
                    public_key=secrets.langfuse_public_key,
                    secret_key=secrets.langfuse_secret_key.get_secret_value(),
                    host=secrets.langfuse_host,
                )
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def question(self, run_id: str, question_id: str) -> Iterator[str]:
        """Open (or join) the trace for one question; yields its trace ID."""
        trace_id = trace_id_for(run_id, question_id)
        if not self.enabled or _current.get() == (run_id, question_id):
            yield trace_id
            return

        from langfuse import propagate_attributes

        token = _current.set((run_id, question_id))
        try:
            with (
                self._client.start_as_current_observation(
                    trace_context={"trace_id": trace_id}, name=f"question {question_id}"
                ),
                propagate_attributes(
                    session_id=run_id,
                    tags=[f"run:{run_id}", f"question:{question_id}"],
                    metadata={"run_id": run_id, "question_id": question_id},
                ),
            ):
                yield trace_id
        finally:
            _current.reset(token)

    @contextmanager
    def tool(self, name: str, tool_input: Mapping[str, Any]) -> Iterator[Any]:
        """A span for one tool call inside the current trace; yields it (None when off)."""
        if not self.enabled:
            yield None
            return
        with self._client.start_as_current_observation(
            name=name, as_type="tool", input=dict(tool_input)
        ) as span:
            yield span

    def llm_callbacks(self) -> list[Any]:
        """LangChain callbacks that record a model call as a generation in the current trace."""
        if not self.enabled:
            return []
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]

    def flush(self) -> None:
        """Send buffered spans; call at the end of a run."""
        if self.enabled:
            self._client.flush()
