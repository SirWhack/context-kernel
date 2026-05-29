"""Verify the re-ingested graph: cross-altitude density + traversal of a merged concept.

Usage: CK_PORTFOLIO=/path/to/project .venv/bin/python scripts/verify_graph.py
"""
import json
import os
import sys
from pathlib import Path
from context_kernel.graph.lightrag_adapter import LightRAGStore
from context_kernel.types import ScopePath

TA = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
if not TA.exists():
    sys.exit("Set CK_PORTFOLIO to the portfolio root (the dir containing .context-kernel).")
store = LightRAGStore(TA / ".context-kernel/graph")
state = json.loads((TA / ".context-kernel/graph/state.json").read_text())
ents = {e["id"]: e for e in state["entities"]}
rels = state["relationships"]

def has_doc(e): return any(s.endswith(".md") for s in e.get("sources", []))
def is_code(e): return any(s.endswith((".py", ".ts", ".tsx", ".js")) for s in e.get("sources", []))

cross = sum(1 for r in rels
            if r["source_id"] in ents and r["target_id"] in ents
            and ((is_code(ents[r["source_id"]]) and has_doc(ents[r["target_id"]]))
                 or (is_code(ents[r["target_id"]]) and has_doc(ents[r["source_id"]]))))
multi = sum(1 for e in ents.values() if len(e.get("sources", [])) >= 2)
codedoc = sum(1 for e in ents.values() if is_code(e) and has_doc(e))

print(f"graph_commit: {str(store.graph_commit())[:16]}…")
print(f"entities={len(ents)}  relationships={len(rels)}")
print(f"multi-source nodes={multi}  code+doc nodes={codedoc}  cross-altitude edges={cross}")

# dynamically pick the concept nodes spanning the most sources (no hardcoded names)
top = sorted((e for e in ents.values() if is_code(e) and has_doc(e)),
             key=lambda e: len(e.get("sources", [])), reverse=True)[:2]
for match in top:
    print(f"\n=== {match['name']} → canonical node ({len(match.get('sources', []))} sources) ===")
    print(f"  kind={match['kind']} kinds={match.get('kinds')} aliases={match.get('aliases')}")
    print(f"  sources: {match.get('sources')}")
    nbrs = store.get_neighbors(match["id"])
    print(f"  neighbors ({len(nbrs)}):")
    for n in nbrs[:12]:
        src = n.entity.sources[0] if n.entity.sources else "?"
        print(f"     --{n.relationship.kind:12}--> {n.entity.name:28} [{n.entity.kind}] {src}")
