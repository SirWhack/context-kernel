"""Aspect-concept classifier — the LLM precision stage for concept grounding.

Implements the "coarse recall -> attention precision" pattern (THOUGHTS.md gap 1):
  1. RECALL  — cheap keyword prefilter over code-entity (name + description) gathers candidates.
                Over-matches by design; that's fine, it only has to be high-recall.
  2. PRECISION — an LLM judges each candidate against the aspect's `definition`, constrained to
                 the provided candidate list (propose-and-drop; no minting -> no confabulation,
                 ADR-0009). Emits confidence per kept edge (ADR-0015 input).

This produces the H3 precision number the keyword proxy in concept_spike.py could not, AND the
proxy's false-positive rate (candidates the LLM rejects). Does NOT mutate the graph.

Usage:
  CK_PORTFOLIO=/path/to/project python scripts/concept_classify.py            # dry-run: plan + cost
  CK_PORTFOLIO=/path/to/project python scripts/concept_classify.py --execute  # calls the LLM
  ... [--limit N] [--batch N] [--min-confidence F] [--only aspect-name]

Reads   $CK_PORTFOLIO/.context-kernel/{graph/state.json, ontology.toml, config.toml}
Writes  $CK_PORTFOLIO/.context-kernel/spike-results/  (local; never committed here)
Auth    api key from env var named by ingester.summarizer_api_key_env (e.g. FOUNDRY_KEY)

Generic / CK_PORTFOLIO-driven, no corpus names — run output may contain real names; don't commit it.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_kernel.config_store import load
from context_kernel.ingester._http import build_client, post_with_retry
from concept_spans import precision_patterns, find_spans   # ADR-0018 evidence oracle

import tomllib

PY = (".py",)
JS = (".ts", ".tsx", ".js", ".jsx")
def _ext(s): return s[s.rfind("."):] if "." in s else ""
def _is_code(e): return any(_ext(s) in PY + JS for s in e.get("sources", []) or [])

_EXCL_DIRS = {".context-kernel", ".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build"}
def _structural_files(root, patterns):
    """Source files matching any of the concern's structural patterns (imports/primitives).

    The recall fix (THOUGHTS.md / h2-benchmarks): keyword-in-description recall misses participants
    whose prose doesn't name the concern. Scanning the real source for primitives catches them.
    """
    regs = [re.compile(p, re.MULTILINE) for p in patterns]
    matched = set()
    for p in root.rglob("*.py"):
        if any(part in _EXCL_DIRS for part in p.parts):
            continue
        try:
            txt = p.read_text(errors="ignore")
        except OSError:
            continue
        if any(r.search(txt) for r in regs):
            matched.add(str(p.relative_to(root)))
    return matched


_EVIDENCE_CACHE = {}
def _file_evidence(root, relpath, patterns, ctx=1, max_lines=12):
    """Source lines in `relpath` matching the concern's structural patterns (+context).

    Experiment 2: by default the judge reasons from name+description and rejects
    structurally-evident-but-description-silent participants. Feeding it the matched source lets it
    confirm them and read off a code-level gotcha.
    """
    if not relpath or not patterns:
        return ""
    key = (relpath, tuple(patterns))
    if key in _EVIDENCE_CACHE:
        return _EVIDENCE_CACHE[key]
    try:
        lines = (root / relpath).read_text(errors="ignore").splitlines()
    except OSError:
        _EVIDENCE_CACHE[key] = ""
        return ""
    regs = [re.compile(p, re.MULTILINE) for p in patterns]
    keep = set()
    for i, ln in enumerate(lines):
        if any(r.search(ln) for r in regs):
            keep.update(range(max(0, i - ctx), min(len(lines), i + ctx + 1)))
        if len(keep) >= max_lines:
            break
    snippet = "\n".join(f"{i+1}: {lines[i].strip()[:100]}" for i in sorted(keep)[:max_lines])
    _EVIDENCE_CACHE[key] = snippet
    return snippet

_SYSTEM = """\
You classify code units by which cross-cutting concern they GENUINELY participate in.
Be strict: a unit participates only if it implements, handles, or directly coordinates the concern
as defined — NOT if it merely mentions the word, imports something related, or lives near it.
When unsure, exclude. Output ONLY JSON, no prose, no fences."""


def _chat(client, endpoint, model, api_key, system, user, max_tokens=1024):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    body = {"model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.1}  # gpt-5.x reasoning models reject 0.0; 0.1 is accepted
    # reasoning models (gpt-5.x / o-series) require max_completion_tokens; others use max_tokens
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
    if model.startswith("deepseek"):
        body["thinking"] = {"type": "disabled"}
    resp = post_with_retry(client, f"{endpoint.rstrip('/')}/chat/completions", json=body, headers=headers)
    return resp.json()["choices"][0]["message"]["content"]


def _parse(raw):
    t = raw.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        return json.loads(t.strip()).get("participants", [])
    except json.JSONDecodeError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="actually call the LLM (default: dry-run)")
    ap.add_argument("--limit", type=int, default=80, help="max candidates per aspect (logged if truncated)")
    ap.add_argument("--batch", type=int, default=12, help="candidates per LLM call")
    ap.add_argument("--min-confidence", type=float, default=0.6)
    ap.add_argument("--only", default=None, help="run a single aspect by name")
    ap.add_argument("--recall", choices=["keyword", "structural", "both"], default="both",
                    help="candidate recall: keyword over description, structural over source, or both")
    args = ap.parse_args()

    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("Set CK_PORTFOLIO to the portfolio root.")
    CK = P / ".context-kernel"
    cfg = load(CK / "config.toml").ingester
    state = json.loads((CK / "graph/state.json").read_text())
    onto = tomllib.loads((CK / "ontology.toml").read_text())["concepts"]
    ents = state["entities"]

    aspects = {n: s for n, s in onto.items()
               if s.get("type") == "aspect" and (not args.only or n == args.only)}

    # ── stage 1: recall (keyword over description, structural over source, or both) ──
    by_id = {e["id"]: e for e in ents}
    recall_src = {}        # aspect -> {"kw": set(ids), "struct": set(ids)}
    candidates = {}
    for name, spec in aspects.items():
        kw_ids, struct_ids = set(), set()
        if args.recall in ("keyword", "both"):
            kws = [k.lower() for k in spec.get("recall_keywords", [])]
            kw_ids = {e["id"] for e in ents if _is_code(e)
                      and any(k in (e["name"] + " " + (e.get("description") or "")).lower() for k in kws)}
        if args.recall in ("structural", "both") and spec.get("structural_patterns"):
            files = _structural_files(P, spec["structural_patterns"])
            # file-level unit: one module entity per matched file (avoids exploding to every
            # nested function/method in a file that merely uses the primitive somewhere).
            struct_ids = {e["id"] for e in ents
                          if (e.get("kind") == "module" or "module" in (e.get("kinds") or []))
                          and any(s in files for s in e.get("sources", []) or [])}
        recall_src[name] = {"kw": kw_ids, "struct": struct_ids}
        # order so truncation keeps the highest-signal first: both signals → structural-only
        # (the recall gain we're measuring) → keyword-only. sorted() makes the truncation
        # deterministic across runs (set iteration order is not stable → reproducible eval).
        ordered = sorted(kw_ids & struct_ids) + sorted(struct_ids - kw_ids) + sorted(kw_ids - struct_ids)
        candidates[name] = [by_id[i] for i in ordered]

    print(f"corpus entities={len(ents)}  aspects={list(aspects)}  recall={args.recall}")
    print("\nstage 1 — recall candidates  (kw=keyword/description, st=structural/source):")
    for name in aspects:
        kw, st = recall_src[name]["kw"], recall_src[name]["struct"]
        trunc = f"  (TRUNCATED to {args.limit})" if len(candidates[name]) > args.limit else ""
        print(f"  {name:16} union={len(candidates[name]):<4} kw={len(kw):<4} st={len(st):<4} "
              f"struct-only={len(st - kw)}{trunc}")
    est_calls = sum((min(len(h), args.limit) + args.batch - 1) // args.batch for h in candidates.values())
    print(f"\nestimated LLM calls: ~{est_calls} (batch={args.batch})")

    if not args.execute:
        print("\n[dry-run] no LLM called. Re-run with --execute to classify.")
        return

    endpoint, model = cfg.summarizer_endpoint, cfg.summarizer_model
    api_key = os.environ.get(cfg.summarizer_api_key_env)
    if not api_key:
        sys.exit(f"Missing API key: set ${cfg.summarizer_api_key_env}")
    client = build_client(timeout=120.0)
    outdir = CK / "spike-results"
    cachedir = outdir / "cache"
    cachedir.mkdir(parents=True, exist_ok=True)

    results = {}
    for name, hits in aspects_iter(candidates, args.limit):
        spec = aspects[name]
        definition = spec.get("definition") or spec.get("prefLabel", name)
        patterns = spec.get("structural_patterns", [])   # broad: drives the judge's evidence display + cache key
        span_pats = precision_patterns(spec)             # strict: drives the emitted CodeSpans (ADR-0018)
        kept, rejected, judged = [], 0, 0
        batch = []
        for e in hits:
            batch.append(e)
            if len(batch) >= args.batch:
                judged += len(batch)
                k, r = _judge(client, endpoint, model, api_key, name, definition, batch,
                              args.min_confidence, cachedir, P, patterns, span_pats)
                kept += k; rejected += r; batch = []
        if batch:
            judged += len(batch)
            k, r = _judge(client, endpoint, model, api_key, name, definition, batch,
                          args.min_confidence, cachedir, P, patterns, span_pats)
            kept += k; rejected += r
        precision = len(kept) / judged if judged else 0.0
        kept_ids = {p["id"] for p in kept}
        st_gain = len(kept_ids & (recall_src[name]["struct"] - recall_src[name]["kw"]))
        with_ev = [p for p in kept if p["evidence_count"]]
        no_ev = [p for p in kept if not p["evidence_count"]]
        ev_precision = len(with_ev) / len(kept) if kept else 0.0
        results[name] = {"judged": judged, "confirmed": len(kept),
                         "rejected_by_llm": rejected, "keyword_proxy_precision": round(precision, 3),
                         "structural_only_confirmed": st_gain,
                         "evidenced": len(with_ev), "no_evidence": len(no_ev),
                         "evidence_precision": round(ev_precision, 3), "participants": kept}
        print(f"\n{name}: judged={judged}  confirmed={len(kept)}  rejected={rejected}  "
              f"precision={precision:.2f}  structural-only-confirmed={st_gain} (recall gain)")
        # ADR-0018 cross-check: LLM-confirmed participants that carry zero strict-primitive evidence.
        print(f"    evidence: {len(with_ev)}/{len(kept)} have a CodeSpan  "
              f"(evidence-precision={ev_precision:.2f})"
              + (f"  ⚠ {len(no_ev)} confirmed-but-no-primitive: "
                 f"{[p['name'] for p in no_ev[:6]]}" if no_ev else ""))

    (outdir / "aspect_classification.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {outdir/'aspect_classification.json'} (local only — do not commit)")
    print("H3: 'keyword-proxy precision' = fraction of keyword candidates the LLM confirmed "
          "(1 - that = the proxy's false-positive rate concept_spike.py couldn't see).")


def aspects_iter(candidates, limit):
    for name, hits in candidates.items():
        yield name, hits[:limit]


def _spans_for(root, sources, span_pats):
    """CodeSpans (content, no line) across a participant's code sources — ADR-0018 evidence leaves."""
    out = []
    for s in sources:
        if _ext(s) not in PY + JS:
            continue
        try:
            txt = (root / s).read_text(errors="ignore")
        except OSError:
            continue
        for sp in find_spans(txt, span_pats):
            out.append({"file": s, **sp})
    return out


def _judge(client, endpoint, model, api_key, aspect, definition, batch, min_conf, cachedir, root, patterns, span_pats=()):
    ev = {}
    for e in batch:
        src = next((s for s in e.get("sources", []) or [] if _ext(s) in PY + JS), None)
        ev[e["id"]] = _file_evidence(root, src, patterns)
    # evidence is part of the prompt → key the cache on it (v2 prevents collision with old caches)
    key = hashlib.sha256(
        ("v2|" + model + "|" + aspect + "|" + definition + "|" +
         "|".join(e["id"] + ":" + ev[e["id"]][:60] for e in batch)).encode()).hexdigest()
    cpath = cachedir / f"{key}.json"
    if cpath.exists():
        parts = json.loads(cpath.read_text())
    else:
        items = []
        for i, e in enumerate(batch):
            src = next((s for s in e.get("sources", []) or [] if _ext(s) in PY + JS), "?")
            indented = "\n".join("     " + ln for ln in (ev[e["id"]] or "(no pattern match)").splitlines())
            items.append(f"{i}. {e['name']} [{e['kind']}] in {src}\n"
                         f"   desc: {(e.get('description') or '')[:110]}\n"
                         f"   source matches:\n{indented}")
        listing = "\n".join(items)
        user = (f"Concern: {aspect}\nDefinition: {definition}\n\n"
                f"Candidate code units, each with the source lines that matched {aspect} patterns:\n"
                f"{listing}\n\n"
                f"Judge from the SOURCE, not the name. Include a unit ONLY if its source genuinely "
                f"implements or coordinates the concern per the definition — NOT merely async I/O, a "
                f"passing mention, or living nearby.\n"
                f'Return ONLY: {{"participants":[{{"id":<number>,"confidence":0.0-1.0,'
                f'"why":"<=6 words","gotcha":"<=12 words: a risk/constraint before changing it, else empty"}}]}}')
        raw = _chat(client, endpoint, model, api_key, _SYSTEM, user, max_tokens=4000)
        parts = _parse(raw) or []
        cpath.write_text(json.dumps(parts))
    kept, rejected = [], 0
    chosen = {p["id"]: p for p in parts if isinstance(p, dict) and "id" in p}
    for i, e in enumerate(batch):
        p = chosen.get(i)
        if p and float(p.get("confidence", 0)) >= min_conf:
            spans = _spans_for(root, e.get("sources", []), span_pats)
            kept.append({"name": e["name"], "id": e["id"], "sources": e.get("sources", []),
                         "confidence": p.get("confidence"), "why": p.get("why", ""),
                         "gotcha": p.get("gotcha", ""),
                         # ADR-0018: evidence leaves. Empty = LLM-confirmed but no strict primitive
                         # → the precision-leak / hallucination-cross-check case (decision-points 5,6).
                         "spans": spans, "evidence_count": len(spans)})
        else:
            rejected += 1
    return kept, rejected


if __name__ == "__main__":
    main()
