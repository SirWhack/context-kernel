"""Cross-module domain primitives. Types only; no behavior."""

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, NewType

# Opaque hash for a Graph state-in-time. See ARCHITECTURE.md §2.1.
GraphCommit = NewType("GraphCommit", str)

# 64-char hex digest used as content-addressed blob filename. See ARCHITECTURE.md §2.2.
Sha256 = NewType("Sha256", str)

# Portfolio-root-relative directory path; the unit of materialization. See ARCHITECTURE.md §2.3.
ScopePath = NewType("ScopePath", Path)


@dataclass(frozen=True)
class ViewSpec:
    """One configured [[view]] entry; rendered by the Materializer."""

    name: str
    kind: str
    params: dict[str, Any]


@dataclass
class LLMMetrics:
    """Thread-safe accumulator for LLM call metrics across one ingestion run."""

    chat_calls: int = 0
    chat_input_tokens: int = 0
    chat_output_tokens: int = 0
    chat_cache_hit_tokens: int = 0
    chat_cache_miss_tokens: int = 0
    embed_calls: int = 0
    embed_input_tokens: int = 0
    total_elapsed_ms: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_chat(
        self,
        input_tokens: int,
        output_tokens: int,
        elapsed_ms: int,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int = 0,
    ) -> None:
        with self._lock:
            self.chat_calls += 1
            self.chat_input_tokens += input_tokens
            self.chat_output_tokens += output_tokens
            self.chat_cache_hit_tokens += cache_hit_tokens
            self.chat_cache_miss_tokens += cache_miss_tokens
            self.total_elapsed_ms += elapsed_ms

    def record_embed(self, input_tokens: int, elapsed_ms: int) -> None:
        with self._lock:
            self.embed_calls += 1
            self.embed_input_tokens += input_tokens
            self.total_elapsed_ms += elapsed_ms

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

    @property
    def prompt_cache_hit_rate(self) -> float:
        total = self.chat_cache_hit_tokens + self.chat_cache_miss_tokens
        return self.chat_cache_hit_tokens / total if total else 0.0

    def estimated_cost_usd(
        self,
        chat_input_rate: float = 0.0,
        chat_output_rate: float = 0.0,
        embed_input_rate: float = 0.0,
        chat_cache_hit_rate: float = 0.0,
    ) -> float:
        """Estimate cost in USD. Rates are $/million tokens."""
        return (
            self.chat_cache_miss_tokens * chat_input_rate / 1_000_000
            + self.chat_cache_hit_tokens * chat_cache_hit_rate / 1_000_000
            + self.chat_output_tokens * chat_output_rate / 1_000_000
            + self.embed_input_tokens * embed_input_rate / 1_000_000
        )
