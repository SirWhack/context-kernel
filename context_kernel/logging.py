"""Structured logging — Parnas-secret: log format. See ARCHITECTURE.md §5."""

from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import datetime, timezone

invocation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "invocation_id", default=None,
)

_EXTRA_KEYS = frozenset({
    "scope", "graph_commit", "duration_ms", "files_written",
    "files_processed", "entities", "relationships",
    "stale_graph_commit", "current_graph_commit", "source_tree_stale",
    "view", "kind",
    "phase_structured_ms", "phase_chunks_ms",
    "phase_embed_entities_ms", "phase_scope_summaries_ms",
    "llm_chat_calls", "llm_chat_input_tokens", "llm_chat_output_tokens",
    "llm_chat_cache_hit_tokens", "llm_chat_cache_miss_tokens",
    "llm_prompt_cache_hit_rate",
    "llm_embed_calls", "llm_embed_input_tokens",
    "llm_total_elapsed_ms", "llm_cache_hits", "llm_cache_misses",
    "llm_estimated_cost_usd",
})


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "invocation": invocation_id.get(),
            "module": record.name,
            "msg": record.getMessage(),
        }
        for key in _EXTRA_KEYS:
            val = getattr(record, key, None)
            if val is not None:
                obj[key] = val
        return json.dumps(obj, default=str)


class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        short_name = record.name.removeprefix("context_kernel.")
        extras = []
        for key in sorted(_EXTRA_KEYS):
            val = getattr(record, key, None)
            if val is not None:
                extras.append(f"{key}={val}")
        inv = invocation_id.get()
        if inv:
            extras.append(f"invocation={inv[:8]}")
        extra_str = " " + " ".join(extras) if extras else ""
        return f"{ts} [{record.levelname}] {short_name}: {record.getMessage()}{extra_str}"


def configure(log_format: str | None = None, log_level: str | None = None) -> None:
    fmt = (log_format or os.environ.get("CK_LOG_FORMAT", "human")).lower()
    level_name = (log_level or os.environ.get("CK_LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = _JsonFormatter() if fmt == "json" else _HumanFormatter()

    root = logging.getLogger("context_kernel")
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.propagate = False
