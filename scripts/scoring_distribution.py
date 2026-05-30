"""Scoring-distribution oracle for the #6 observational eval.

Reads a re-ingested graph and reports the confidence / centrality / drift
distributions the scoring mechanism (ADR-0015/0019/0020) actually produced on a
real corpus — split by entity class (code / doc / prose) so we can see whether
the axes discriminate the way the ADRs claim.

Usage: CK_PORTFOLIO=/path/to/portfolio PYTHONPATH=. .venv/bin/python scripts/scoring_distribution.py
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

TA = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
if not TA.exists():
    sys.exit("Set CK_PORTFOLIO to the portfolio root (the dir containing .context-kernel).")
state = json.loads((TA / ".context-kernel/graph/state.json").read_text())
ents = state["entities"]
rels = state["relationships"]

CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
def is_code(e): return any(s.endswith(CODE_EXT) for s in e.get("sources", []))
def has_doc(e): return any(s.endswith(".md") for s in e.get("sources", []))

def klass(e):
    c, d = is_code(e), has_doc(e)
    if c and d: return "code+doc"
    if c: return "code"
    if d: return "doc"
    return "prose"

def quantiles(xs):
    if not xs: return "(none)"
    s = sorted(xs)
    n = len(s)
    q = lambda p: s[min(n - 1, int(p * n))]
    return f"min={s[0]:.3f}  p25={q(.25):.3f}  med={q(.5):.3f}  p75={q(.75):.3f}  max={s[-1]:.3f}  mean={sum(s)/n:.3f}"

print(f"entities={len(ents)}  relationships={len(rels)}\n")

# ── Confidence / source_tier / centrality by class ──────────────────────────
by_class = {}
for e in ents:
    by_class.setdefault(klass(e), []).append(e)

print("── per-class scoring (count | source_tier | confidence | centrality) ──")
print(f"{'class':9} {'n':>4}  {'tier(med)':>9}  {'conf(med)':>9}  {'cen>0':>6}  {'cen(max)':>8}")
for k in ("code", "doc", "code+doc", "prose"):
    g = by_class.get(k, [])
    if not g: continue
    tiers = sorted(e.get("source_tier", 0.0) for e in g)
    confs = sorted(e.get("confidence", 1.0) for e in g)
    cens = [e.get("centrality", 0.0) for e in g]
    cen_nz = sum(1 for c in cens if c > 0)
    med = lambda xs: xs[len(xs)//2] if xs else 0.0
    print(f"{k:9} {len(g):>4}  {med(tiers):>9.3f}  {med(confs):>9.3f}  {cen_nz:>6}  {max(cens):>8.3f}")

print("\n── confidence quantiles, all entities ──")
print("  " + quantiles([e.get("confidence", 1.0) for e in ents]))
print("── source_tier histogram ──")
for tier, n in sorted(Counter(round(e.get("source_tier", 0.0), 2) for e in ents).items()):
    print(f"  tier {tier:.2f}: {n}")

# ── Drift: where did confidence actually drop below authority? ───────────────
drifted = [e for e in ents if e.get("confidence", 1.0) < e.get("source_tier", 0.0) - 1e-9]
print(f"\n── drift effect: {len(drifted)} entities have confidence < source_tier (drift bit) ──")
for e in sorted(drifted, key=lambda e: e.get("confidence", 1.0))[:15]:
    gap = e.get("source_tier", 0.0) - e.get("confidence", 1.0)
    print(f"  {e['name'][:38]:38} tier={e.get('source_tier'):.2f} conf={e.get('confidence'):.3f}  Δ={gap:.3f}  {e.get('sources')}")

# ── Edge drift distribution ─────────────────────────────────────────────────
edge_drift = [r.get("drift", 0.0) for r in rels]
nz_edge = [d for d in edge_drift if d > 0]
print(f"\n── edge drift: {len(nz_edge)}/{len(rels)} edges carry drift>0 ──")
if nz_edge:
    print("  " + quantiles(nz_edge))
print("── edge-kind histogram ──")
for kind, n in sorted(Counter(r["kind"] for r in rels).items(), key=lambda x: -x[1]):
    print(f"  {kind:14} {n}")

# ── Centrality leaders ──────────────────────────────────────────────────────
central = sorted((e for e in ents if e.get("centrality", 0.0) > 0),
                 key=lambda e: -e.get("centrality", 0.0))
print(f"\n── centrality leaders ({len(central)} nonzero) ──")
for e in central[:12]:
    print(f"  cen={e.get('centrality'):.3f}  conf={e.get('confidence'):.3f}  {e['name'][:40]:40} {klass(e)}")
