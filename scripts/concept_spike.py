"""Concept-layer spike: ground a curated ontology onto an existing graph, measure bridging.

Tests the concept-layer hypotheses (THOUGHTS.md / thoughts-spiked.md) against a live, already-
ingested graph WITHOUT mutating it and WITHOUT any LLM call:

  - entity-concept → deterministic alias-match → `implemented-by` (H1 recall; H3 precision by eye)
  - aspect-concept → keyword-over-description → `participates-in` *candidates*. This is a CHEAP
    PROXY for the real LLM classifier (thoughts-spiked H1/H3); its precision is NOT verified here —
    keyword substring matching over-matches by design. Treat aspect numbers as an upper bound /
    feasibility probe (topology, scatter), not as the classifier's real recall/precision.

Reports per-concept bridging (code files / docs / languages), H4 topology (concepts-per-symbol and
concept sizes), and a traversal sample over the graph's typed edges.

Usage:  CK_PORTFOLIO=/path/to/project python scripts/concept_spike.py
Reads:  $CK_PORTFOLIO/.context-kernel/graph/state.json
        $CK_PORTFOLIO/.context-kernel/ontology.toml   (local, never committed here)

Generic / CK_PORTFOLIO-driven, no corpus names — same sanitization discipline as the sibling
measurement scripts. Run output may contain real names; do not commit it.
"""
import collections
import os
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from context_kernel.ingester.entity_resolver import normalize

import json

P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
if not P.exists():
    sys.exit("Set CK_PORTFOLIO to the portfolio root (the dir containing .context-kernel).")
CK = P / ".context-kernel"
state = json.loads((CK / "graph/state.json").read_text())
onto = tomllib.loads((CK / "ontology.toml").read_text())["concepts"]

ents = state["entities"]
rels = state["relationships"]
by_id = {e["id"]: e for e in ents}

PY = (".py",)
JS = (".ts", ".tsx", ".js", ".jsx")
MD = (".md",)
def _ext(s): return s[s.rfind("."):] if "." in s else ""
def _langs(srcs):
    out = set()
    for s in srcs:
        e = _ext(s)
        if e in PY: out.add("py")
        elif e in JS: out.add("js")
        elif e in MD: out.add("md")
    return out
def _is_code(e): return any(_ext(s) in PY + JS for s in e.get("sources", []) or [])

# adjacency over typed edges (for the traversal sample)
adj = collections.defaultdict(list)
for r in rels:
    adj[r["source_id"]].append((r["kind"], r["target_id"], "→"))
    adj[r["target_id"]].append((r["kind"], r["source_id"], "←"))


def ground_entity(spec):
    want = {normalize(a) for a in (spec.get("altLabel") or []) + [spec.get("prefLabel", "")] if a}
    hits = []
    for e in ents:
        names = [e["name"], *(e.get("aliases") or [])]
        if any(normalize(n) in want for n in names):
            hits.append(e)
    return hits


def ground_aspect(keywords):
    kws = [k.lower() for k in keywords]
    hits = []
    for e in ents:
        if not _is_code(e):
            continue                       # aspect participants = code, not prose-about-it
        blob = (e["name"] + " " + (e.get("description") or "")).lower()
        if any(k in blob for k in kws):
            hits.append(e)
    return hits


def bridge_stats(hits):
    srcs = set()
    for e in hits:
        srcs.update(e.get("sources", []) or [])
    langs = _langs(srcs)
    code = sorted(s for s in srcs if _ext(s) in PY + JS)
    docs = sorted(s for s in srcs if _ext(s) in MD)
    return srcs, langs, code, docs


print(f"corpus: entities={len(ents)} relationships={len(rels)}\n")
print("=" * 78)
print("ENTITY-CONCEPTS — deterministic alias grounding (implemented-by)")
print("=" * 78)

sym_concepts = collections.defaultdict(set)   # code symbol id -> {concept} (H4)
concept_sizes = {}
bridged = 0
for name, spec in onto.items():
    if spec.get("type") != "entity":
        continue
    hits = ground_entity(spec)
    srcs, langs, code, docs = bridge_stats(hits)
    concept_sizes[name] = len(hits)
    for e in hits:
        if _is_code(e):
            sym_concepts[e["id"]].add(name)
    is_bridged = bool(code) and bool(docs)
    bridged += is_bridged
    flag = "BRIDGED" if is_bridged else "       "
    print(f"\n[{flag}] {name}  (nodes={len(hits)}, langs={sorted(langs)}, "
          f"code_files={len(code)}, docs={len(docs)})")
    print(f"    code: {[s.split('/')[-1] for s in code[:5]]}")
    print(f"    docs: {[s.split('/')[-1] for s in docs[:8]]}")
    if spec.get("broader") or spec.get("related"):
        print(f"    skos: broader={spec.get('broader') or []} related={spec.get('related') or []}")

print(f"\n→ {bridged}/{sum(1 for s in onto.values() if s.get('type')=='entity')} "
      f"entity-concepts bridge code AND docs")

print("\n" + "=" * 78)
print("ASPECT-CONCEPTS — keyword proxy for the LLM classifier (participates-in)")
print("  ** precision UNVERIFIED — upper-bound / scatter probe only **")
print("=" * 78)
for name, spec in onto.items():
    if spec.get("type") != "aspect":
        continue
    hits = ground_aspect(spec["recall_keywords"])
    files = sorted({s for e in hits for s in e.get("sources", []) or [] if _ext(s) in PY + JS})
    concept_sizes[name] = len(hits)
    for e in hits:
        sym_concepts[e["id"]].add(name)
    print(f"\n{name}: code participants={len(hits)} across {len(files)} files")
    print(f"    files: {[s.split('/')[-1] for s in files[:8]]}")

print("\n" + "=" * 78)
print("H4 TOPOLOGY — is the symbol×concept graph navigable or a hairball?")
print("=" * 78)
cps = collections.Counter(len(v) for v in sym_concepts.values())
multi = {sid: c for sid, c in sym_concepts.items() if len(c) > 1}
print(f"code symbols touched by a concept: {len(sym_concepts)}")
print(f"concepts-per-symbol distribution: {dict(sorted(cps.items()))}")
print(f"symbols in >1 concept (many-to-many): {len(multi)}")
print(f"concept sizes: {dict(sorted(concept_sizes.items(), key=lambda kv: -kv[1]))}")

print("\n" + "=" * 78)
print("TRAVERSAL SAMPLE — a concept hub's typed neighbors (what an agent would walk)")
print("=" * 78)
for name, spec in onto.items():
    if spec.get("type") != "entity":
        continue
    hits = [e for e in ground_entity(spec) if _is_code(e)]
    if not hits:
        continue
    anchor = max(hits, key=lambda e: len(adj[e["id"]]))
    nbrs = adj[anchor["id"]]
    print(f"\n{name} → {anchor['name']} ({anchor['kind']}, {len(nbrs)} edges):")
    seen = set()
    for kind, tid, arrow in nbrs:
        t = by_id.get(tid)
        if not t or tid in seen:
            continue
        seen.add(tid)
        src = (t.get("sources") or ["?"])[0].split("/")[-1]
        print(f"    {arrow} {kind:12} {t['name'][:34]:34} [{t['kind']}] {src}")
        if len(seen) >= 8:
            break
    break   # one representative hub is enough for the sample
