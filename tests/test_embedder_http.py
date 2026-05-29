"""Unit tests for the batched embedder + shared retry plumbing (no network)."""

import struct

import httpx
import pytest

from context_kernel.ingester import _http
from context_kernel.ingester.embedder import HttpEmbedder


def _emb_response(texts, *, shuffle=False):
    """Build an OpenAI-style embeddings payload, optionally with out-of-order indices."""
    order = list(range(len(texts)))
    if shuffle:
        order = order[::-1]
    data = [{"index": i, "embedding": [float(i), float(i) + 0.5]} for i in order]
    return {"data": data, "usage": {"prompt_tokens": len(texts)}}


def _embedder_with_handler(handler):
    emb = HttpEmbedder("http://test/v1", "model-x", dim=2, api_key="k")
    emb._client = httpx.Client(transport=httpx.MockTransport(handler))
    return emb


def test_embed_batch_sends_array_and_realigns_by_index():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen["body"] = json.loads(request.content)
        # Return indices reversed to prove the embedder realigns to input order.
        return httpx.Response(200, json=_emb_response(seen["body"]["input"], shuffle=True))

    emb = _embedder_with_handler(handler)
    out = emb.embed_batch(["a", "b", "c"], mode="passage")

    assert seen["body"]["input"] == ["a", "b", "c"]  # sent as one array
    assert len(out) == 3
    # index 0 -> [0.0, 0.5], index 1 -> [1.0, 1.5], index 2 -> [2.0, 2.5]
    assert out[0] == struct.pack("2f", 0.0, 0.5)
    assert out[1] == struct.pack("2f", 1.0, 1.5)
    assert out[2] == struct.pack("2f", 2.0, 2.5)


def test_embed_single_delegates_to_batch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_emb_response(["only"]))

    emb = _embedder_with_handler(handler)
    assert emb.embed("only") == struct.pack("2f", 0.0, 0.5)


def test_embed_batch_empty_is_noop():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not POST for empty input")

    emb = _embedder_with_handler(handler)
    assert emb.embed_batch([]) == []


def test_post_with_retry_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda _s: None)  # no real backoff waits
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resp = _http.post_with_retry(client, "http://test/v1/x", json={})
    assert resp.status_code == 200
    assert calls["n"] == 3


def test_post_with_retry_raises_after_exhausting(monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda _s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        _http.post_with_retry(client, "http://test/v1/x", json={}, max_retries=2)
