#!/usr/bin/env python3
"""Prototype: embedding-based cross-altitude linker (doc concept -> code entity).

The graph extracts doc concepts ("Advanced Vector Database Support", a `decision`) and code
symbols (`VectorDBBase`) into the same vector space but never connects them — name-merge
needs lexical overlap (prose vs symbol = none) and the LLM extractor emits ~0 cross edges.
This pass bridges them by MEANING: for each doc concept, find the top-N code entities by
cosine similarity above a threshold and propose a semantic edge.

Read-only by default — reports the similarity distribution + sample links so we can pick a
threshold and judge precision before wiring it into ingest. `CK_PORTFOLIO=<repo>`.

  CK_PORTFOLIO=test-repos/open-webui .venv/bin/python scripts/cross_altitude_link.py
  CK_PORTFOLIO=test-repos/open-webui .venv/bin/python scripts/cross_altitude_link.py --sample 25
"""
import argparse
import math
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_kernel.config_store import load
from context_kernel.agent_cli import _build_store

CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx")
# Doc-concept kinds worth linking to code (ADR-0013 taxonomy); skip pure governance noise.
DOC_KINDS = {"decision", "constraint", "invariant", "interface", "workflow", "trade-off", "risk"}


def _unpack(b: bytes) -> list[float]:
    if not b:
        return []
    return list(struct.unpack(f"{len(b)//4}f", b))


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) if len(a) == len(b) and a else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=18, help="doc concepts to show with top matches")
    ap.add_argument("--topn", type=int, default=3)
    args = ap.parse_args()

    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("set CK_PORTFOLIO to the repo root")
    os.environ["CK_CONFIG_PATH"] = str(P / ".context-kernel" / "config.toml")
    store = _build_store(load().portfolio_root)

    ents = store._entities
    # entity embedding = the entity-kind chunk whose id is the entity id
    emb = {c.id: _norm(_unpack(c.embedding)) for c in store._chunks if c.kind == "entity"}

    def is_code(e):
        return any(str(s).endswith(CODE_EXT) for s in e.sources)

    def is_doc(e):
        return any(str(s).endswith(".md") for s in e.sources) and not is_code(e)

    docs = [e for e in ents.values() if is_doc(e) and e.kind in DOC_KINDS and emb.get(e.id)]
    code = [(e, emb[e.id]) for e in ents.values() if is_code(e) and emb.get(e.id)]
    print(f"doc concepts (linkable): {len(docs)}   code entities: {len(code)}")
    if not docs or not code:
        return 0

    # best code match per doc concept
    best = []  # (doc, [(code_ent, sim), ...top-n])
    for d in docs:
        dv = emb[d.id]
        sims = sorted(((c, _dot(dv, cv)) for c, cv in code), key=lambda t: t[1], reverse=True)
        best.append((d, sims[:args.topn]))

    tops = [b[1][0][1] for b in best if b[1]]
    tops.sort()
    print("\ntop-1 cosine distribution across doc concepts:")
    for thr in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        n = sum(1 for t in tops if t >= thr)
        print(f"  >= {thr:.2f} : {n:3} docs ({100*n/len(tops):.0f}%) would link")
    print(f"  median top-1 = {tops[len(tops)//2]:.3f}   max = {tops[-1]:.3f}   min = {tops[0]:.3f}")

    print(f"\nsample doc-concept -> top-{args.topn} code matches (judge precision):")
    step = max(1, len(best) // args.sample)
    for d, sims in best[::step][:args.sample]:
        print(f"\n  [{d.kind}] {d.name!r}")
        for c, s in sims:
            src = next((str(x) for x in c.sources if str(x).endswith(CODE_EXT)), "?")
            print(f"      {s:.3f}  {c.name}  ({src.split('/')[-1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
