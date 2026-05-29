"""Measurement harness: run the real entity_resolver on reconstructed raw extractions.

AST for code + summarizer cache for docs (cache hits, no LLM). No graph mutation.
Validates the shipped resolver module on the live corpus before wiring it into the
ingester. Embeddings are omitted here, so the collision guard leaves ambiguous-name
docs as concept nodes (precision-safe lower bound on connectivity).

Usage: CK_PORTFOLIO=/path/to/project .venv/bin/python scripts/resolver_prototype.py
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from context_kernel.change_detection import walk_source_files
from context_kernel.config_store import load
from context_kernel.ingester import _STRUCTURED, _CHUNK
from context_kernel.ingester.summarizer import _cache_key
from context_kernel.ingester.entity_resolver import (
    ExtractedEntity, ExtractedRelationship, resolve, normalize,
)

TA = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
if not TA.exists():
    sys.exit("Set CK_PORTFOLIO to the portfolio root (the dir containing .context-kernel).")
cfg = load(TA / ".context-kernel/config.toml")
MODEL = cfg.ingester.summarizer_model
CACHE = TA / ".context-kernel/cache"

ents: list[ExtractedEntity] = []
rels: list[ExtractedRelationship] = []
for f in walk_source_files(TA):
    rel = str(f.relative_to(TA))
    h = next((h for h in _STRUCTURED if h.supports(f)), None)
    if h:
        re_, rr_ = h.extract(f)
        ents += [ExtractedEntity(e.name, e.kind, rel, e.description) for e in re_]
        rels += [ExtractedRelationship(r.source_name, r.target_name, r.kind, rel, r.description) for r in rr_]
        continue
    ch = next((h for h in _CHUNK if h.supports(f)), None)
    if ch:
        for chunk in ch.chunks(f):
            cp = CACHE / f"{_cache_key(chunk, MODEL)}.json"
            if not cp.exists():
                continue
            d = json.loads(cp.read_text())
            ents += [ExtractedEntity(e["name"], e.get("kind",""), rel, e.get("description","")) for e in d.get("entities", []) if e.get("name")]
            rels += [ExtractedRelationship(r["source_name"], r["target_name"], r.get("kind",""), rel, r.get("description","")) for r in d.get("relationships", []) if r.get("source_name") and r.get("target_name")]

nodes, edges, stats = resolve(ents, rels)
print("=== entity_resolver on live corpus (no embeddings → precision-safe lower bound) ===")
for k, v in stats.items():
    print(f"  {k:24} {v}")

byname = defaultdict(list)
for n in nodes:
    byname[normalize(n.name)].append(n)

# collision guard: pick whatever name maps to the most distinct code definitions
multi_code = [(nm, ns) for nm, ns in byname.items() if sum(1 for x in ns if x.is_code) > 1]
if multi_code:
    nm, ns = max(multi_code, key=lambda kv: len(kv[1]))
    print(f"\n=== collision guard: {nm!r} kept distinct across code defs? ===")
    for n in ns:
        print(f"  is_code={n.is_code} sources={n.sources}")

# the merged node spanning the most sources (code + docs)
codedoc = [n for n in nodes if n.is_code and any(s.endswith(".md") for s in n.sources)]
if codedoc:
    top = max(codedoc, key=lambda n: len(n.sources))
    print(f"\n=== top code+doc merged node: {top.name!r} ({len(top.sources)} sources) ===")
    print(f"  is_code={top.is_code} kinds={top.kinds} sources={top.sources}")
