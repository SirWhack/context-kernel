"""Materialize concept hubs into a resolve-concept view surface.

The fix the H2 round-1 review pointed at: the concept hubs carry exact code paths + governing ADRs,
but they were never materialized where an agent could reach them, so the kernel arm fell back to
`find`/`overview` and guessed file paths. This writes each concept as a markdown hub under
`.context-kernel/views/concepts/`, the way the Materializer renders cross-cutting views — giving a
`resolve-concept` surface with **exact source paths** AND the governing decisions.

Grounding (no embeddings — identity stays curated, per THOUGHTS.md):
  - entity-concept → deterministic alias-match (altLabel + prefLabel)
  - aspect-concept → the LLM-confirmed participants from `spike-results/aspect_classification.json`
                     if present; else the keyword-recall set, clearly flagged UNVERIFIED.
Governing docs/ADRs come from traversing the graph's typed edges (governed-by / implements /
motivates / …) out of each grounded node. Reads the graph; does NOT mutate `state.json`.

Usage:  CK_PORTFOLIO=/path/to/project python scripts/concept_materialize.py
Reads   $CK_PORTFOLIO/.context-kernel/{graph/state.json, ontology.toml,
        spike-results/aspect_classification.json (optional)}
Writes  $CK_PORTFOLIO/.context-kernel/views/concepts/{<key>.md, index.md}  (local; do not commit)

Generic / CK_PORTFOLIO-driven, no corpus names.
"""
import json
import os
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_kernel.ingester.entity_resolver import normalize
from concept_spans import locate   # ADR-0018: re-derive a span's CURRENT line at render time

PY = (".py",); JS = (".ts", ".tsx", ".js", ".jsx"); MD = (".md",)
def _ext(s): return s[s.rfind("."):] if "." in s else ""
def _code_srcs(e): return sorted({s for s in e.get("sources", []) or [] if _ext(s) in PY + JS})
def _doc_srcs(e): return sorted({s for s in e.get("sources", []) or [] if _ext(s) in MD})
def _is_code(e): return bool(_code_srcs(e))
def _is_doc(e): return bool(_doc_srcs(e))


def main():
    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("Set CK_PORTFOLIO to the portfolio root.")
    CK = P / ".context-kernel"
    state = json.loads((CK / "graph/state.json").read_text())
    onto = tomllib.loads((CK / "ontology.toml").read_text())["concepts"]
    cls_path = CK / "spike-results/aspect_classification.json"
    classified = json.loads(cls_path.read_text()) if cls_path.exists() else {}
    eg_path = CK / "spike-results/entity_gotchas.json"
    entity_gotchas = json.loads(eg_path.read_text()) if eg_path.exists() else {}

    ents = state["entities"]
    by_id = {e["id"]: e for e in ents}
    adj = defaultdict(list)
    for r in state["relationships"]:
        adj[r["source_id"]].append((r["kind"], r["target_id"], "→"))
        adj[r["target_id"]].append((r["kind"], r["source_id"], "←"))

    def ground_entity(spec):
        want = {normalize(a) for a in (spec.get("altLabel") or []) + [spec.get("prefLabel", "")] if a}
        return [e for e in ents
                if any(normalize(n) in want for n in [e["name"], *(e.get("aliases") or [])])]

    def governing(nodes):
        """Docs/ADRs reachable from a concept's grounded nodes, via typed edges + own doc sources."""
        gov = {}   # doc source -> set of edge kinds
        for n in nodes:
            for s in _doc_srcs(n):
                gov.setdefault(s, set()).add("describes")
            for kind, oid, _ in adj.get(n["id"], []):
                t = by_id.get(oid)
                if t and _is_doc(t):
                    for s in _doc_srcs(t):
                        gov.setdefault(s, set()).add(kind)
        return gov

    _src_cache = {}
    def src_text(rel):
        if rel not in _src_cache:
            try:
                _src_cache[rel] = (P / rel).read_text(errors="ignore")
            except OSError:
                _src_cache[rel] = ""
        return _src_cache[rel]

    outdir = CK / "views/concepts"
    outdir.mkdir(parents=True, exist_ok=True)
    index_rows = []

    for key, spec in onto.items():
        pref = spec.get("prefLabel", key)
        defn = spec.get("definition", "")
        typ = spec.get("type", "entity")
        gotchas = []
        ev_leaves = None      # ADR-0018: when set, aspect renders evidence spans instead of bare files
        flagged = []          # LLM-confirmed participants carrying no strict primitive (decision-pt 5/6)

        if typ == "entity":
            nodes = ground_entity(spec)
            code_nodes = [n for n in nodes if _is_code(n)]
            impl = []
            for n in code_nodes:
                for s in _code_srcs(n):
                    impl.append((s, n["name"], n.get("kind", "")))
            gov = governing(nodes)
            ground_note = f"entity · alias-match · {len(nodes)} nodes"
            gotchas = entity_gotchas.get(key, [])
        else:
            conf = classified.get(key, {})
            parts = conf.get("participants")
            if parts is not None:
                # ADR-0018: split LLM-confirmed participants by whether they carry a CodeSpan.
                evidenced = [p for p in parts if p.get("spans")]
                flagged = [p for p in parts if not p.get("spans")]
                # evidence leaves: (file, derived_line, snippet, owner) — line relocated in CURRENT source
                seen_leaf = {}      # (file, line, snippet) → first owner; dedups module-vs-class doubles
                for p in evidenced:
                    for sp in p.get("spans", []):
                        f = sp.get("file", "")
                        k = (f, locate(src_text(f), sp), sp.get("snippet", ""))
                        seen_leaf.setdefault(k, p["name"])
                ev_leaves = sorted(((f, line, snip, owner) for (f, line, snip), owner in seen_leaf.items()),
                                   key=lambda t: (t[0], t[1] or 0))
                impl = [(s, p["name"], "") for p in evidenced for s in p.get("sources", []) if _ext(s) in PY + JS]
                ground_note = (f"aspect · evidence-grounded · {len(evidenced)}/{len(parts)} with CodeSpan "
                               f"(evidence-precision {conf.get('evidence_precision','?')})")
                nodes = [by_id[p["id"]] for p in evidenced if p.get("id") in by_id]
                gotchas = sorted({p["gotcha"].strip() for p in evidenced if p.get("gotcha", "").strip()})
            else:
                kws = [k.lower() for k in spec.get("recall_keywords", [])]
                nodes = [e for e in ents if _is_code(e)
                         and any(k in (e["name"] + " " + (e.get("description") or "")).lower() for k in kws)]
                impl = [(s, n["name"], n.get("kind", "")) for n in nodes for s in _code_srcs(n)]
                ground_note = f"aspect · keyword-recall · {len(nodes)} candidates · ⚠ UNVERIFIED (run concept_classify.py)"
            gov = governing(nodes)

        impl = sorted(set(impl))
        related = (spec.get("related") or []) + [f"{b} (broader)" for b in (spec.get("broader") or [])]

        lines = [f"# {pref}  (`{key}`)", ""]
        if defn:
            lines += [f"> {defn}", ""]
        if ev_leaves is not None:
            # ADR-0018: aspect concept = its evidence spans. Each leaf carries file:line + the
            # actual primitive line, re-derived in current source — the receipt grep computes live.
            lines.append("**Participates (code, evidence-grounded)**")
            if ev_leaves:
                for f, line, snippet, owner in ev_leaves[:50]:
                    loc = f"`{f}:{line}`" if line else f"`{f}` _(primitive moved/removed)_"
                    lines.append(f"- {loc} — `{snippet}`  ({owner})")
                if len(ev_leaves) > 50:
                    lines.append(f"- … +{len(ev_leaves)-50} more")
            else:
                lines.append("- _(no coordination primitive grounded)_")
            if flagged:
                lines += ["", "**⚠ Unverified — LLM-claimed but no primitive in source**"]
                for p in flagged[:12]:
                    src = next((s for s in p.get("sources", []) if _ext(s) in PY + JS), "?")
                    lines.append(f"- `{src}` — {p['name']}  _(confidence {p.get('confidence','?')}; treat as a lead, not a fact)_")
        else:
            lines.append("**Implemented by**" if typ == "entity" else "**Participates (code, candidates)**")
            if impl:
                for s, nm, kind in impl[:50]:
                    lines.append(f"- `{s}` — {nm}{(' ['+kind+']') if kind else ''}")
                if len(impl) > 50:
                    lines.append(f"- … +{len(impl)-50} more")
            else:
                lines.append("- _(none grounded)_")
        lines += ["", "**Documented / governed by**"]
        if gov:
            for s, kinds in sorted(gov.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:14]:
                lines.append(f"- `{s}`  ({'/'.join(sorted(kinds))})")
            if len(gov) > 14:
                lines.append(f"- … +{len(gov)-14} more docs")
        else:
            lines.append("- _(none)_")
        if gotchas:
            lines += ["", "**Gotchas (from source)**"] + [f"- {g}" for g in gotchas[:8]]
        if related:
            lines += ["", "**Related**"] + [f"- `{r}`" for r in related]
        lines += ["", f"<sub>grounding: {ground_note} · generated by concept_materialize.py · do not edit</sub>", ""]
        (outdir / f"{key}.md").write_text("\n".join(lines))
        index_rows.append((key, pref, typ, len({s for s, _, _ in impl}), len(gov), ground_note))

    idx = ["# Concepts — resolve-concept surface", "",
           "Curated concept hubs grounded onto code + governing docs. Ask by concept; each page lists",
           "exact implementation paths and the decisions that govern them. Generated; do not edit.", "",
           "| concept | type | code files | docs | grounding |", "|---|---|---|---|---|"]
    for key, pref, typ, ncode, ndoc, note in sorted(index_rows, key=lambda r: (r[2], r[0])):
        idx.append(f"| [{pref}](./{key}.md) (`{key}`) | {typ} | {ncode} | {ndoc} | {note} |")
    (outdir / "index.md").write_text("\n".join(idx) + "\n")

    print(f"materialized {len(index_rows)} concept hubs → {outdir}")
    for key, pref, typ, ncode, ndoc, note in index_rows:
        print(f"  {key:20} {typ:6} code_files={ncode:<3} docs={ndoc:<3} [{note}]")


if __name__ == "__main__":
    main()
