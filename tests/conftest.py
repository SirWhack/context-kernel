"""Shared test fixtures — auto-launch llama-server for embedding tests."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from context_kernel.ingester.embedder import HttpEmbedder


@pytest.fixture(autouse=True)
def _reset_ck_logger():
    """Reset the context_kernel logger between tests so configure() state doesn't leak."""
    yield
    root = logging.getLogger("context_kernel")
    root.handlers.clear()
    root.propagate = True
    root.setLevel(logging.WARNING)

_EMBEDDER_PORT = 8081
_EMBEDDER_URL = f"http://127.0.0.1:{_EMBEDDER_PORT}"
_SERVER_BIN = Path.home() / "src/llama.cpp/build/bin/llama-server"
_MODEL_PATH = Path.home() / "models/qwen3-embedding-0.6b/Qwen3-Embedding-0.6B-Q8_0.gguf"
_STARTUP_TIMEOUT = 30


def _server_healthy() -> bool:
    try:
        r = httpx.get(f"{_EMBEDDER_URL}/health", timeout=2.0)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


@pytest.fixture(scope="session")
def embedder():
    """Session-scoped HttpEmbedder backed by a real llama-server."""
    if _server_healthy():
        yield HttpEmbedder(
            endpoint=f"{_EMBEDDER_URL}/v1",
            model="qwen3-embedding-0.6b",
            dim=1024,
        )
        return

    if not _SERVER_BIN.exists():
        pytest.skip(f"llama-server not found at {_SERVER_BIN}")
    if not _MODEL_PATH.exists():
        pytest.skip(f"Embedding model not found at {_MODEL_PATH}")

    proc = subprocess.Popen(
        [
            str(_SERVER_BIN),
            "-m", str(_MODEL_PATH),
            "--embeddings",
            "-ngl", "99",
            "--port", str(_EMBEDDER_PORT),
            "--pooling", "last",
            "--no-mmap",
            "--cache-ram", "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"llama-server exited with code {proc.returncode}")
        if _server_healthy():
            break
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip(f"llama-server did not become healthy within {_STARTUP_TIMEOUT}s")

    yield HttpEmbedder(
        endpoint=f"{_EMBEDDER_URL}/v1",
        model="qwen3-embedding-0.6b",
        dim=1024,
    )

    proc.terminate()
    proc.wait(timeout=5)
