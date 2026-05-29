"""Embedder — hides which model produces vector embeddings. See ARCHITECTURE.md §2.2."""

from __future__ import annotations

import logging
import struct
import time
from typing import TYPE_CHECKING, Literal, Protocol

from context_kernel.ingester._http import build_client, post_with_retry

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

    def embed_batch(
        self, texts: list[str], *, mode: Literal["passage", "query"] = "passage"
    ) -> list[bytes]:
        """Embed many texts in one round-trip. Returns embeddings aligned to `texts`."""
        ...


class HttpEmbedder:
    """Embedder backed by an OpenAI-compatible endpoint.

    Reuses one keep-alive `httpx.Client` across calls (and across the ingest's worker
    threads — the client is thread-safe) so we don't re-handshake TLS per request.
    """

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
        self._client = build_client(timeout=30.0)

    def embed(self, text: str, *, mode: Literal["passage", "query"] = "passage") -> bytes:
        return self.embed_batch([text], mode=mode)[0]

    def embed_batch(
        self, texts: list[str], *, mode: Literal["passage", "query"] = "passage"
    ) -> list[bytes]:
        if not texts:
            return []
        if mode == "query":
            texts = [f"{_QUERY_INSTRUCT}{t}" for t in texts]

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        t0 = time.monotonic()
        resp = post_with_retry(
            self._client,
            f"{self._endpoint}/embeddings",
            json={"input": texts, "model": self._model},
            headers=headers or None,
        )
        data = resp.json()
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0) or usage.get("total_tokens", 0)
        if self._metrics:
            self._metrics.record_embed(input_tokens, elapsed_ms)

        # The API may return items out of order; realign to the input order via `index`.
        items = sorted(data["data"], key=lambda d: d["index"])
        out: list[bytes] = []
        for item in items:
            floats = item["embedding"]
            out.append(struct.pack(f"{len(floats)}f", *floats))
        return out
