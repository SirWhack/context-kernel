#!/usr/bin/env python3
"""Sync local Context Kernel graph to Cloudflare KV + Neon Postgres (pgvector).

Reads:
  - .context-kernel/graph/state.json  (chunk metadata)
  - .context-kernel/graph/chunks/*.bin (1024-dim float32 embeddings)
  - <portfolio>/<scope>/AGENTS.md      (materialized overviews)

Uploads:
  - KV: scope summaries (key: scope:<path>, value: markdown body)
  - Neon: chunk embeddings + metadata into pgvector table

Env vars:
  CF_API_TOKEN     — Cloudflare API token (KV write)
  CF_ACCOUNT_ID    — Cloudflare account ID (or CF_USER)
  KV_NAMESPACE_ID  — KV namespace ID for SUMMARIES
  DATABASE_URL     — Neon Postgres connection string

Usage:
  source .env
  python3 cloud/mcp-server/sync.py --portfolio ~/Code
"""

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

import requests

PORTFOLIO_DEFAULT = Path.home() / "Code"
INSERT_BATCH_SIZE = 200

HEADER_RE = re.compile(
    r"<!--\s*context-kernel-freshness\s*\n"
    r"graph:\s*[0-9a-f]+\s*\n"
    r"source-tree:\s*[0-9a-f]+\s*\n"
    r"materialized:\s*\S+\s*\n"
    r"-->"
)

SCHEMA_SQL = """\
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    embedding vector(1024) NOT NULL,
    chunk_text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_scope_idx ON chunks (scope);
"""


def strip_header(text: str) -> str:
    m = HEADER_RE.search(text)
    if not m:
        return text
    return text[m.end():].lstrip("\n")


def load_state(portfolio: Path) -> dict:
    state_path = portfolio / ".context-kernel" / "graph" / "state.json"
    if not state_path.exists():
        sys.exit(f"Graph not found at {state_path}. Run 'ck ingest' first.")
    with open(state_path) as f:
        return json.load(f)


def collect_agents_md(portfolio: Path) -> dict[str, str]:
    scopes: dict[str, str] = {}
    for agents_path in portfolio.rglob("AGENTS.md"):
        if any(p in agents_path.parts for p in (".venv", "node_modules", ".git", ".context-kernel")):
            continue
        scope = str(agents_path.parent.relative_to(portfolio))
        if scope == ".":
            continue
        text = agents_path.read_text(encoding="utf-8")
        body = strip_header(text)
        if body.strip():
            scopes[scope] = body
    return scopes


def upload_kv(scopes: dict[str, str], account_id: str, namespace_id: str, token: str) -> int:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/bulk"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    pairs = [{"key": f"scope:{scope}", "value": text} for scope, text in scopes.items()]
    pairs.append({"key": "scopes:index", "value": json.dumps(sorted(scopes.keys()))})

    batch_size = 100
    total = 0
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i : i + batch_size]
        resp = requests.put(url, headers=headers, json=batch)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("success"):
            sys.exit(f"KV bulk write failed: {result.get('errors')}")
        total += len(batch)
        print(f"  KV: uploaded {total}/{len(pairs)} keys")

    return len(pairs) - 1


def upload_vectors(state: dict, chunks_dir: Path, database_url: str) -> int:
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        sys.exit("psycopg2 not found. Install with: pip install psycopg2-binary")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    print("  Ensuring schema...")
    for statement in SCHEMA_SQL.split(";"):
        statement = statement.strip()
        if statement:
            cur.execute(statement)
    conn.commit()

    chunks = state.get("chunks", [])
    uploaded = 0
    skipped = 0

    for batch_start in range(0, len(chunks), INSERT_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + INSERT_BATCH_SIZE]
        rows = []

        for chunk in batch:
            bin_path = chunks_dir / f"{chunk['id']}.bin"
            if not bin_path.exists():
                skipped += 1
                continue

            raw = bin_path.read_bytes()
            n = len(raw) // 4
            values = list(struct.unpack(f"{n}f", raw))
            vector_str = f"[{','.join(str(v) for v in values)}]"

            rows.append((
                chunk["id"],
                vector_str,
                chunk.get("chunk_text", ""),
                chunk.get("source_path", ""),
                chunk.get("kind", ""),
                chunk.get("scope", ""),
            ))

        if not rows:
            continue

        execute_values(
            cur,
            """INSERT INTO chunks (id, embedding, chunk_text, source_path, kind, scope)
               VALUES %s
               ON CONFLICT (id) DO UPDATE SET
                   embedding = EXCLUDED.embedding,
                   chunk_text = EXCLUDED.chunk_text,
                   source_path = EXCLUDED.source_path,
                   kind = EXCLUDED.kind,
                   scope = EXCLUDED.scope""",
            rows,
            template="(%s, %s::vector, %s, %s, %s, %s)",
        )
        conn.commit()
        uploaded += len(rows)
        print(f"  Neon: upserted {uploaded}/{len(chunks)} vectors (skipped {skipped} missing .bin)")

    cur.close()
    conn.close()
    return uploaded


def main():
    parser = argparse.ArgumentParser(description="Sync Context Kernel graph to Cloudflare KV + Neon")
    parser.add_argument("--portfolio", type=Path, default=PORTFOLIO_DEFAULT)
    parser.add_argument("--vectors-only", action="store_true", help="Skip KV upload, only sync vectors")
    parser.add_argument("--kv-only", action="store_true", help="Skip vector upload, only sync KV")
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID") or os.environ.get("CF_USER")
    token = os.environ.get("CF_API_TOKEN")
    namespace_id = os.environ.get("KV_NAMESPACE_ID")
    database_url = os.environ.get("DATABASE_URL")

    if not args.vectors_only:
        if not account_id:
            sys.exit("Set CF_ACCOUNT_ID (or CF_USER) env var")
        if not token:
            sys.exit("Set CF_API_TOKEN env var")
        if not namespace_id:
            sys.exit("Set KV_NAMESPACE_ID env var")

    if not args.kv_only:
        if not database_url:
            sys.exit("Set DATABASE_URL env var (Neon connection string)")

    portfolio = args.portfolio.expanduser().resolve()
    print(f"Portfolio: {portfolio}")

    n_kv = 0
    n_vec = 0

    if not args.vectors_only:
        print("\nCollecting AGENTS.md files...")
        scopes = collect_agents_md(portfolio)
        print(f"Found {len(scopes)} scopes")
        print("\nUploading to KV...")
        n_kv = upload_kv(scopes, account_id, namespace_id, token)
        print(f"Done: {n_kv} scopes in KV")

    if not args.kv_only:
        print("\nLoading graph state...")
        state = load_state(portfolio)
        chunks_dir = portfolio / ".context-kernel" / "graph" / "chunks"
        n_chunks = len(state.get("chunks", []))
        print(f"Found {n_chunks} chunks")
        print("\nUploading to Neon...")
        n_vec = upload_vectors(state, chunks_dir, database_url)
        print(f"Done: {n_vec} vectors in Neon")

    print(f"\nSync complete: {n_kv} scopes, {n_vec} vectors")


if __name__ == "__main__":
    main()
