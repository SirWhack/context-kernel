#!/usr/bin/env python3
"""Deterministic A/B for ADR-0023 query-time neighbor expansion.

Measures the *retrieval* effect of expansion in isolation — no sonnet agent, no LLM, no cost,
no run-to-run noise. For each "why"-shaped model-time question it runs the real retrieval +
ranking stack twice (expansion off, then on) and reports where the gold file lands in the
ranked results. Expansion should pull a gold ADR/code node that sits one hop from the obvious
vector hit into view; where the vector search already nails the gold, expansion is a correct
no-op.

Isolates retrieval from the token-budget truncation in `find()` by calling
`nearest_chunks` + `rank_by_relevance` directly and reading the ordered source paths.

  set -a; source .env; set +a            # local embedder needs no key, but harmless
  PYTHONPATH=. .venv/bin/python scripts/expansion_ab.py
  PYTHONPATH=. .venv/bin/python scripts/expansion_ab.py --k 10 --topn 6
"""
import argparse
import dataclasses
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CK_CONFIG_PATH", str(Path("/home/swynn/Code/.context-kernel/config.toml")))

from context_kernel.config_store import load
from context_kernel.agent_cli import _build_store, _build_embedder, _resolve_api_key
from context_kernel.orientation_server.tools import nearest_chunks, rank_by_relevance
from context_kernel.scoring import ScoringConfig

# Each question: a "why/what-governs" query + the gold source-path substrings that answer it.
# Gold is deliberately a doc/ADR (or the code) that a strong vector hit is connected to by a
# governs/realizes/motivates edge — the cross-altitude hop expansion is meant to expose.
BATTERY = [
    ("why can't a coding agent ever read a stale materialized file?",
     ["freshness_gate.py", "0020-staleness", "theory.md"]),
    ("what decision governs how the graph commit is computed?",
     ["0008-content-derived-graph-commit"]),
    ("why does the ingester use two different handler protocols for source files?",
     ["0011-two-handler-protocols", "handlers.py"]),
    ("what strategy resolves a code definition and the docs describing it into one node?",
     ["0017-entity-resolution", "entity_resolver.py"]),
    ("why is staleness modeled as structural drift instead of elapsed time?",
     ["0020-staleness-as-structural-drift"]),
    ("what decision defines how entity confidence is scored?",
     ["0015-entity-confidence-scoring", "scoring.py"]),
    ("why is regeneration enforced at commit time rather than pulled on demand?",
     ["0003-pull-based-jit", "0010-", "freshness_gate.py"]),
    ("what governs the taxonomy of entities extracted from markdown?",
     ["0013-markdown-entity-taxonomy", "handlers.py"]),
    ("why is relevance composed at query time but confidence materialized at ingest?",
     ["0019-confidence-materialized", "scoring.py"]),
    ("what makes the find score combine similarity with graph proximity?",
     ["0015-entity-confidence-scoring", "0019-confidence-materialized", "tools.py"]),
]


def _gold_rank(ranked, gold, topn):
    for i, r in enumerate(ranked[:topn]):
        path = (r.source_path or "").lower()
        if any(g.lower() in path for g in gold):
            return i + 1  # 1-based rank
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10, help="vector top-k seed pool")
    ap.add_argument("--topn", type=int, default=6, help="rank window scored for a gold hit")
    args = ap.parse_args()

    cfg = load()
    store = _build_store(cfg.portfolio_root)
    embedder = _build_embedder(cfg, _resolve_api_key(cfg.ingester.embedder_api_key_env))

    off = dataclasses.replace(ScoringConfig.resolve(env=os.environ), expansion_enabled=False)
    on = dataclasses.replace(ScoringConfig.resolve(env=os.environ), expansion_enabled=True)

    print(f"expansion A/B over {len(BATTERY)} model-time 'why' questions  (k={args.k} topn={args.topn})\n")
    helped = hurt = same_hit = same_miss = 0
    for q, gold in BATTERY:
        # Retrieve ONCE; apply both rankings to the same seed set so the only variable is
        # expansion — re-retrieving per arm would inject vector-search noise (duplicate-chunk
        # reordering) and fabricate off/on deltas.
        results = nearest_chunks(q, store, embedder, k=args.k, scope=None)
        ro = _gold_rank(rank_by_relevance(results, store, off), gold, args.topn)
        rn = _gold_rank(rank_by_relevance(results, store, on), gold, args.topn)
        if ro is None and rn is not None:
            verdict, sym = "EXPANSION SURFACED gold", "✓+"; helped += 1
        elif ro is not None and rn is None:
            verdict, sym = "expansion LOST gold (regression)", "✗-"; hurt += 1
        elif ro is None and rn is None:
            verdict, sym = "neither found gold in window", "··"; same_miss += 1
        elif rn < ro:
            verdict, sym = f"rank {ro}->{rn} (lifted)", "✓"; helped += 1
        elif rn > ro:
            verdict, sym = f"rank {ro}->{rn} (pushed down)", "✗"; hurt += 1
        else:
            verdict, sym = f"rank {ro} (no change)", "="; same_hit += 1
        print(f"  {sym:3} off={str(ro):>4} on={str(rn):>4}  {verdict}")
        print(f"        Q: {q}")
    print(f"\nsummary: helped={helped}  hurt={hurt}  unchanged-hit={same_hit}  "
          f"unchanged-miss={same_miss}")
    print("(helped = gold newly surfaced or lifted; hurt = lost or pushed down. A no-op where "
          "the vector hit already nailed it is correct, not a failure.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
