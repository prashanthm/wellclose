"""Langfuse tracing + correlation ids (Brief §6.3, T8.1). Per-LLM-call cost attribution lives on
the LLM client; this module provides safe-noop tracing when Langfuse keys are absent."""
import os
import uuid
from contextlib import contextmanager

_lf = None


def _client():
    global _lf
    if _lf is None and os.getenv("LANGFUSE_PUBLIC_KEY"):
        try:
            from langfuse import Langfuse
            _lf = Langfuse()
        except Exception:
            _lf = False
    return _lf or None


def new_run_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def span(name: str, run_id: str | None = None, well_id: str | None = None,
         document_id: str | None = None, **meta):
    lf = _client()
    trace = None
    if lf:
        trace = lf.trace(name=name, id=run_id, metadata={"well_id": well_id,
                         "document_id": document_id, **meta})
    try:
        yield trace
    finally:
        if lf:
            lf.flush()
