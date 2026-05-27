"""Embedder — hides which model produces vector embeddings. See ARCHITECTURE.md §2.2."""

from __future__ import annotations

import logging
import struct
import time
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from context_kernel.types import LLMMetrics

log = logging.getLogger(__name__)

_QUERY_INSTRUCT = (
    "Instruct: Find relevant code modules, classes, functions, "
    "or documentation in a software portfolio.\n"
    "Query: "
)


class Embedder(Protocol):
    """Produce a dense vector embedding for a text chunk."""

    def embed(self, text: str, *, mode: Literal["passage", "query"] = "passage") -> bytes:
        """Return the serialized embedding. Caller addresses it via Sha256."""
        ...


class HttpEmbedder:
    """Embedder backed by an OpenAI-compatible endpoint."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        dim: int = 1024,
        *,
        api_key: str | None = None,
        metrics: "LLMMetrics | None" = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._dim = dim
        self._api_key = api_key
        self._metrics = metrics

    def embed(self, text: str, *, mode: Literal["passage", "query"] = "passage") -> bytes:
        if mode == "query":
            text = f"{_QUERY_INSTRUCT}{text}"

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        t0 = time.monotonic()
        resp = httpx.post(
            f"{self._endpoint}/embeddings",
            json={"input": text, "model": self._model},
            headers=headers or None,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0) or usage.get("total_tokens", 0)

        if self._metrics:
            self._metrics.record_embed(input_tokens, elapsed_ms)

        floats = data["data"][0]["embedding"]
        return struct.pack(f"{len(floats)}f", *floats)
