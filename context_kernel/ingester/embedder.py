"""Embedder Parnas-secret — hides which model produces vector embeddings. See ARCHITECTURE.md §2.2."""

from __future__ import annotations

import struct
from typing import Literal, Protocol

import httpx

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
    """Embedder backed by a llama-server OpenAI-compatible endpoint."""

    def __init__(self, endpoint: str, model: str, dim: int = 1024) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._dim = dim

    def embed(self, text: str, *, mode: Literal["passage", "query"] = "passage") -> bytes:
        if mode == "query":
            text = f"{_QUERY_INSTRUCT}{text}"

        resp = httpx.post(
            f"{self._endpoint}/embeddings",
            json={"input": text, "model": self._model},
            timeout=30.0,
        )
        resp.raise_for_status()
        floats = resp.json()["data"][0]["embedding"]
        return struct.pack(f"{len(floats)}f", *floats)
