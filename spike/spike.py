#!/usr/bin/env python3
"""S0 validation spike — run LightRAG against the LifeStrands corpus via
llama-server endpoints, measure the four S0 exit criteria.

Throwaway. The architecture lives in ARCHITECTURE.md and docs/slices/.
"""
import asyncio, time, json, sys, os
from pathlib import Path

import httpx
import numpy as np
import networkx as nx
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status

# ---------------------------- configuration -------------------------------

PORTFOLIO_ROOT = Path(os.environ.get("PORTFOLIO_ROOT", "/home/swynn/Code/LifeStrands"))

LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://127.0.0.1:8080/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "qwen3-30b")

EMBED_ENDPOINT = os.environ.get("EMBED_ENDPOINT", "http://127.0.0.1:8081/v1")
EMBED_MODEL    = os.environ.get("EMBED_MODEL", "qwen3-embedding-0.6b")
EMBED_DIM      = 1024

_safe = LLM_MODEL.replace(".", "_").replace("-", "_").replace("/", "_")
WORKING_DIR = Path(os.environ.get("WORKING_DIR", f"./spike_storage_{_safe}"))

INCLUDE_EXTS = {".py", ".md", ".sql"}
# If set, only files whose path-relative-to-root starts with one of these prefixes
# are included (root-level files are always included).
_inc = os.environ.get("INCLUDE_PREFIXES", "")
INCLUDE_PREFIXES = tuple(p for p in _inc.split(":") if p)
EXCLUDE_PATH_PARTS = {
    ".git", "__pycache__", "venv", ".venv", "node_modules",
    "dist", "build", ".next", "test-env", "Orpheus-FastAPI",
    "dia", "model_cache", "audio_output", "test_audio_output",
    "assets", "reviews", "logs", "backups", "pids", "frontends",
    ".pytest_cache", ".vscode", ".claude", ".playwright-mcp", "misc",
    "monitoring", "nginx", "pgadmin", "scripts", "tests",
}

GRAPH_FIELD_SEP = "<SEP>"

# ---------------------------- LightRAG plumbing ---------------------------

async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    return await openai_complete_if_cache(
        LLM_MODEL, prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key="not-needed", base_url=LLM_ENDPOINT,
        temperature=0.2,
        **kwargs,
    )

async def embed_func(texts, **_):
    """Direct HTTP to llama-server /v1/embeddings. Bypasses lightrag.llm.openai.openai_embed
    which forces `dimensions=1536` via a decorator and doesn't match Qwen3-Embedding-0.6B (1024)."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    async with httpx.AsyncClient(timeout=120.0) as cx:
        # Llama-server accepts batched inputs but can drop items silently under load;
        # send sequentially for reliability during the spike.
        for i, text in enumerate(texts):
            r = await cx.post(
                f"{EMBED_ENDPOINT}/embeddings",
                json={"input": text, "model": EMBED_MODEL},
            )
            r.raise_for_status()
            data = r.json()["data"]
            vec = data[0]["embedding"]
            if len(vec) != EMBED_DIM:
                raise ValueError(f"got dim={len(vec)} expected {EMBED_DIM}")
            out[i] = vec
    return out

embedding_func = EmbeddingFunc(
    embedding_dim=EMBED_DIM, max_token_size=8192, func=embed_func,
)

async def make_rag():
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    rag = LightRAG(
        working_dir=str(WORKING_DIR),
        llm_model_func=llm_model_func,
        llm_model_name=LLM_MODEL,
        embedding_func=embedding_func,
        # Match llama-server --parallel 1; queueing on the server side adds
        # latency without throughput gain.
        llm_model_max_async=1,
        embedding_batch_num=8,
        embedding_func_max_async=2,
        entity_extract_max_gleaning=1,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag

# ---------------------------- corpus walker -------------------------------

def collect_files(root: Path):
    files = []
    for p in root.rglob("*"):
        if not p.is_file(): continue
        if p.suffix.lower() not in INCLUDE_EXTS: continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_PATH_PARTS for part in rel.parts): continue
        if INCLUDE_PREFIXES:
            rel_str = str(rel)
            # always include root-level files (no directory in path)
            at_root = "/" not in rel_str
            if not at_root and not rel_str.startswith(INCLUDE_PREFIXES):
                continue
        files.append(p)
    return sorted(files)

def scope_of(file_path: str, root: Path) -> str:
    p = Path(file_path)
    rel = p.relative_to(root) if p.is_absolute() else p
    return str(rel.parent) if rel.parent != Path('.') else '.'

# ---------------------------- commands ------------------------------------

async def cmd_ingest():
    files = collect_files(PORTFOLIO_ROOT)
    max_files = int(os.environ.get("MAX_FILES", "0"))
    if max_files > 0:
        files = files[:max_files]
    scopes = {scope_of(str(f), PORTFOLIO_ROOT) for f in files}
    print(f"Corpus: {len(files)} files across {len(scopes)} scopes"
          + (f" (MAX_FILES={max_files})" if max_files else ""))
    print(f"LLM model tag: {LLM_MODEL} @ {LLM_ENDPOINT}")
    print(f"Working dir:   {WORKING_DIR}")

    rag = await make_rag()
    texts, paths, ids = [], [], []
    for f in files:
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            print(f"  skip {f}: {e}"); continue
        if not content.strip(): continue
        texts.append(content); paths.append(str(f)); ids.append(str(f))

    print(f"Inserting {len(texts)} non-empty files...")
    t0 = time.time()
    await rag.ainsert(texts, ids=ids, file_paths=paths)
    dt = time.time() - t0
    print(f"\nIngest complete: {dt:.1f}s wall ({dt/len(texts):.2f}s/file avg)")

async def cmd_measure():
    graph_path = WORKING_DIR / "graph_chunk_entity_relation.graphml"
    if not graph_path.exists():
        print(f"No graph at {graph_path}; run `ingest` first.")
        return
    G = nx.read_graphml(graph_path)
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    print(f"Entities:      {n_nodes}")
    print(f"Relationships: {n_edges}")

    def scopes_for(node_id):
        attrs = G.nodes[node_id]
        fp_blob = attrs.get('file_path', '') or ''
        scopes = set()
        for s in fp_blob.split(GRAPH_FIELD_SEP):
            s = s.strip()
            if not s or s == 'unknown_source':
                continue
            try:
                scopes.add(scope_of(s, PORTFOLIO_ROOT))
            except ValueError:
                scopes.add(s)
        return scopes

    cross, total = 0, 0
    multi_evidence = 0  # endpoints in >1 distinct scopes (the ADR-0009 def)
    edges_per_scope_pair = {}
    for u, v in G.edges():
        total += 1
        scopes = scopes_for(u) | scopes_for(v)
        if len(scopes) > 1:
            cross += 1
            for s1 in scopes:
                for s2 in scopes:
                    if s1 < s2:
                        edges_per_scope_pair[(s1, s2)] = edges_per_scope_pair.get((s1, s2), 0) + 1

    pct = (cross/total*100) if total else 0
    print(f"\nCross-scope density (ADR-0009): {cross}/{total} = {pct:.1f}%")
    if pct >= 15:
        verdict = "GO (≥15%)"
    elif pct < 5:
        verdict = "STOP — re-grill ADR-0004 (<5%)"
    else:
        verdict = "LIMP (5-15%)"
    print(f"  → {verdict}")

    print(f"\nTop cross-scope edge pairs:")
    for (s1, s2), n in sorted(edges_per_scope_pair.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:4d}  {s1}  ↔  {s2}")

async def cmd_synthesize(scope: str):
    """First-read latency proxy: gather one scope's entities/rels and send to
    the LLM with an S1-style synthesis prompt. Measure wall time."""
    graph_path = WORKING_DIR / "graph_chunk_entity_relation.graphml"
    if not graph_path.exists():
        print(f"No graph at {graph_path}; run `ingest` first.")
        return
    G = nx.read_graphml(graph_path)

    def scopes_for(node_id):
        fp_blob = G.nodes[node_id].get('file_path', '') or ''
        scopes = set()
        for s in fp_blob.split(GRAPH_FIELD_SEP):
            s = s.strip()
            if not s or s == 'unknown_source': continue
            try: scopes.add(scope_of(s, PORTFOLIO_ROOT))
            except ValueError: scopes.add(s)
        return scopes

    in_scope = {n for n in G.nodes() if scope in scopes_for(n)}
    if not in_scope:
        print(f"No entities found in scope '{scope}'. Available scopes (sample):")
        seen = set()
        for n in list(G.nodes())[:200]:
            seen.update(scopes_for(n))
        for s in sorted(seen)[:30]:
            print(f"  {s}")
        return

    print(f"Scope '{scope}': {len(in_scope)} entities")
    entities_text = []
    for n in list(in_scope)[:50]:
        attrs = G.nodes[n]
        entities_text.append(f"- {n} ({attrs.get('entity_type','?')}): {attrs.get('description','')[:200]}")
    within, cross = [], []
    for u, v, data in G.edges(data=True):
        if u in in_scope and v in in_scope:
            within.append(f"- {u} → {v}: {data.get('description','')[:150]}")
        elif u in in_scope or v in in_scope:
            other = v if u in in_scope else u
            other_scope = next(iter(scopes_for(other) - {scope}), '?')
            cross.append(f"- {u} → {v} ({other_scope}): {data.get('description','')[:150]}")
    within = within[:40]; cross = cross[:40]
    print(f"  within-scope relationships: {len(within)} (sample)")
    print(f"  cross-scope relationships:  {len(cross)} (sample)")

    prompt = f"""You are documenting a directory in a software portfolio for a coding agent
that has never seen this codebase. The agent needs orientation — what's in
this scope, what's important, and how it relates to the rest of the
portfolio — to know where to look first.

Scope: {scope}

Entities extracted from this scope:
{chr(10).join(entities_text)}

Relationships within this scope:
{chr(10).join(within)}

Relationships crossing to other scopes:
{chr(10).join(cross)}

Write a ~500-token markdown orientation. Name canonical file paths in prose
so the reader can Read them directly. Do not list files. Do not list
entities. Write prose."""

    print(f"\nSynthesizing scope '{scope}' (prompt ~{len(prompt)//4} tokens)...")
    t0 = time.time()
    result = await llm_model_func(prompt)
    dt = time.time() - t0
    print(f"\n--- Synthesis took {dt:.1f}s ---")
    print(result)
    print("\n" + "=" * 70)
    print(f"First-read latency proxy: {dt:.1f}s ({'PASS' if dt < 60 else 'FAIL'} vs 60s threshold)")

async def cmd_query(question: str):
    rag = await make_rag()
    t0 = time.time()
    result = await rag.aquery(question, param=QueryParam(mode="hybrid", top_k=20))
    print(f"--- query took {time.time()-t0:.1f}s ---\n{result}")

# ---------------------------- entry ---------------------------------------

USAGE = """Usage:
  python spike.py ingest                  # ingest the corpus
  python spike.py measure                 # cross-scope density (ADR-0009)
  python spike.py synthesize <scope>      # first-read latency proxy
  python spike.py query <question>        # sanity-check hybrid query

Environment:
  LLM_MODEL=<tag>                         # default: qwen3-30b
  LLM_ENDPOINT=http://host:port/v1        # default: localhost:8080
  EMBED_ENDPOINT=http://host:port/v1      # default: localhost:8081
  PORTFOLIO_ROOT=/path/to/repo            # default: /home/swynn/Code/LifeStrands
  WORKING_DIR=./path                      # default: ./spike_storage_<llm_model>
"""

def main():
    if len(sys.argv) < 2:
        print(USAGE); sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "ingest":
        asyncio.run(cmd_ingest())
    elif cmd == "measure":
        asyncio.run(cmd_measure())
    elif cmd == "synthesize" and len(sys.argv) > 2:
        asyncio.run(cmd_synthesize(sys.argv[2]))
    elif cmd == "query" and len(sys.argv) > 2:
        asyncio.run(cmd_query(sys.argv[2]))
    else:
        print(USAGE); sys.exit(2)

if __name__ == "__main__":
    main()
