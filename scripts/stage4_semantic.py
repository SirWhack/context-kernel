"""Measure Stage 4 semantic linking over the existing graph (no re-ingest, no LLM).

Usage: CK_PORTFOLIO=/path/to/project .venv/bin/python scripts/stage4_semantic.py [threshold]
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

from context_kernel.ingester.semantic_linker import semantic_links

_ROOT = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
if not _ROOT.exists():
    sys.exit("Set CK_PORTFOLIO to the portfolio root (the dir containing .context-kernel).")
TA = _ROOT / ".context-kernel"
state = json.loads((TA / "graph/state.json").read_text())
ents = state["entities"]
rels = state["relationships"]
chunks_dir = TA / "graph/chunks"

CODE_EXT = (".py", ".ts", ".tsx", ".js")
def is_code(e): return e["kind"] in {"module", "class", "function"} or any(s.endswith(CODE_EXT) for s in e.get("sources", []))

ids, embs, codeflags, byid = [], [], [], {}
for e in ents:
    p = chunks_dir / f"{e['id']}.bin"
    if not p.exists():
        continue
    v = np.frombuffer(p.read_bytes(), dtype=np.float32)
    if v.size == 0:
        continue
    ids.append(e["id"]); embs.append(v); codeflags.append(is_code(e)); byid[e["id"]] = e
E = np.vstack(embs)
existing = {(r["source_id"], r["target_id"]) for r in rels}
n_concept = sum(1 for c in codeflags if not c)
n_code = sum(codeflags)
print(f"nodes with embeddings={len(ids)} (concept={n_concept}, code={n_code}, dim={E.shape[1]})")

for th in (0.85, 0.80, 0.75):
    links = semantic_links(ids, E, codeflags, existing, k=5, threshold=th, max_per_node=3)
    covered = len({c for c, _, _ in links})
    print(f"\n=== threshold={th}: {len(links)} related edges, {covered} concept nodes newly linked to code ===")
    if th == float(sys.argv[1]) if len(sys.argv) > 1 else th == 0.80:
        for c, k, s in sorted(links, key=lambda x: -x[2])[:12]:
            cn, kn = byid[c]["name"], byid[k]["name"]
            ksrc = next((x for x in byid[k].get("sources", []) if x.endswith(CODE_EXT)), "?")
            print(f"   {s:.3f}  \"{cn[:34]}\"  ~related~  {kn}  ({ksrc})")
