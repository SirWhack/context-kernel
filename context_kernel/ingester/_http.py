"""Shared HTTP plumbing for the LLM/embedding clients: connection pooling + retry.

Both `HttpEmbedder` and `LLMSummarizer` talk to OpenAI-compatible endpoints over
many small POSTs. Two concerns live here so they stay consistent:

1. A persistent `httpx.Client` (keep-alive pool) so we don't pay a fresh TCP+TLS
   handshake per request — material when a single ingest makes thousands of calls.
2. Bounded retry with exponential backoff + jitter on 429 / 5xx / transport errors,
   honoring `Retry-After`. Without this, raising `parallel_requests` would turn rate
   limits into silently-dropped entities. `httpx.Client` is thread-safe, so one
   client is shared across the ingest's worker threads.
"""

from __future__ import annotations

import logging
import random
import time

import httpx

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_S = 30.0


def build_client(*, timeout: float, max_connections: int = 64) -> httpx.Client:
    """A keep-alive client sized to comfortably cover the configured concurrency."""
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_connections,
        keepalive_expiry=30.0,
    )
    return httpx.Client(timeout=timeout, limits=limits)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)  # delta-seconds form; HTTP-date form is rare here and we fall back to backoff
    except ValueError:
        return None


def _backoff_seconds(attempt: int) -> float:
    return min(2.0 ** attempt, _MAX_BACKOFF_S) + random.uniform(0.0, 0.5)


def post_with_retry(
    client: httpx.Client,
    url: str,
    *,
    json: dict,
    headers: dict[str, str] | None = None,
    max_retries: int = 5,
) -> httpx.Response:
    """POST with bounded retry on 429/5xx/transport errors. Raises on final failure."""
    attempt = 0
    while True:
        try:
            resp = client.post(url, json=json, headers=headers)
        except httpx.TransportError as exc:
            if attempt >= max_retries:
                raise
            delay = _backoff_seconds(attempt)
            log.warning("POST %s transport error (%s); retry %d/%d in %.1fs",
                        url, exc, attempt + 1, max_retries, delay)
            time.sleep(delay)
            attempt += 1
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < max_retries:
            retry_after = _retry_after_seconds(resp)
            # Add jitter even on top of Retry-After so concurrent callers that all
            # got the same window don't re-fire in lockstep (thundering herd).
            delay = (retry_after + random.uniform(0.0, 5.0)) if retry_after is not None else _backoff_seconds(attempt)
            log.warning("POST %s -> %d; retry %d/%d in %.1fs",
                        url, resp.status_code, attempt + 1, max_retries, delay)
            time.sleep(delay)
            attempt += 1
            continue

        resp.raise_for_status()
        return resp
