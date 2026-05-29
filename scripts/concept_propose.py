"""Ontology cold-start bootstrapper — propose-then-curate (never auto-adopt).

The mature ontology-engineering pattern (AIO / ODK; THOUGHTS.md ontology-design notes): mine
candidate vocabulary from STRUCTURE the operator definitely uses, let an LLM nominate a draft
ontology constrained to that vocabulary, then the operator curates. Crucially it does NOT mine
prose for concepts and embed-match to code — that is the path the 0.42 measurement already closed.

Mines three structural signals from the existing graph (no LLM):
  1. identifier tokens   — CamelCase/snake_case pieces of code symbol names, by frequency
  2. path segments       — directory names (modules/areas), by frequency
  3. doc-anchored symbols— code symbols that documentation actually names (strong entity-concepts)
Then (--execute) asks the LLM to group them into 8-20 SKOS concepts (prefLabel, type, altLabel
drawn ONLY from mined terms, one-line definition, optional broader). Writes a *draft* the operator
edits into ontology.toml. LLM membership is trusted; LLM-proposed hierarchy needs human review.

Usage:
  CK_PORTFOLIO=/path python scripts/concept_propose.py            # dry-run: show mined vocabulary
  CK_PORTFOLIO=/path python scripts/concept_propose.py --execute  # LLM nominates; writes a draft

Reads   $CK_PORTFOLIO/.context-kernel/{graph/state.json, config.toml}
Writes  $CK_PORTFOLIO/.context-kernel/spike-results/ontology.draft.toml   (local; never committed)
Auth    api key from env named by ingester.summarizer_api_key_env (e.g. FOUNDRY_KEY)

Generic / CK_PORTFOLIO-driven, no corpus names — output may contain real names; don't commit it.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from context_kernel.config_store import load
from context_kernel.ingester._http import build_client, post_with_retry
from context_kernel.ingester.entity_resolver import normalize

PY = (".py",); JS = (".ts", ".tsx", ".js", ".jsx"); MD = (".md",)
def _ext(s): return s[s.rfind("."):] if "." in s else ""
def _is_code(e): return any(_ext(s) in PY + JS for s in e.get("sources", []) or [])
def _is_md(e): return any(_ext(s) in MD for s in e.get("sources", []) or [])

# noise tokens that carry no concept identity
_STOP = frozenset({"test", "tests", "init", "main", "self", "args", "kwargs", "none", "true",
                   "false", "return", "value", "type", "types", "base", "util", "utils", "conf",
                   "conftest", "module", "class", "func", "impl", "data", "info", "item", "list",
                   "dict", "name", "names", "path", "file", "files"})
_STOP_SEG = frozenset({"src", "tests", "test", "scripts", "__pycache__", "static", "js", "core"})


def tok(name):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.replace("_", " "))
    return [t.lower() for t in s.split() if len(t) >= 4 and t.lower() not in _STOP]


def mine(state):
    ents = state["entities"]
    code = [e for e in ents if _is_code(e)]
    tokf = collections.Counter()
    for e in code:
        for t in set(tok(e["name"])):
            tokf[t] += 1
    segf = collections.Counter()
    for e in code:
        for s in e.get("sources", []) or []:
            if _ext(s) in PY + JS:
                for seg in s.split("/")[:-1]:
                    if seg and seg not in _STOP_SEG and len(seg) >= 3:
                        segf[seg] += 1
    # doc-anchored code symbols: code name that also appears as a doc entity name, by #docs
    docnames = collections.defaultdict(set)
    for e in ents:
        if _is_md(e):
            for s in e.get("sources", []) or []:
                if _ext(s) in MD:
                    docnames[normalize(e["name"])].add(s)
    anchored = []
    for e in code:
        n = normalize(e["name"])
        if n in docnames:
            anchored.append((len(docnames[n]), e["name"]))
    anchored = [nm for _, nm in sorted(anchored, reverse=True)]
    # dedup anchored by name preserving order
    seen = set(); anchored = [x for x in anchored if not (x in seen or seen.add(x))]
    return tokf, segf, anchored


def _chat(client, endpoint, model, api_key, system, user, max_tokens=3000):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}], "temperature": 0.1}
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
    if model.startswith("deepseek"):
        body["thinking"] = {"type": "disabled"}
    resp = post_with_retry(client, f"{endpoint.rstrip('/')}/chat/completions", json=body, headers=headers)
    return resp.json()["choices"][0]["message"]["content"]


_SYSTEM = """\
You bootstrap a DRAFT concept ontology for a codebase, to be curated by a human afterward.
You are given vocabulary mined from the code's STRUCTURE (identifier tokens, directory names, and
the code symbols that documentation references). Group it into 8-20 concepts.

Each concept is one of two flavors:
  - "entity": a thing the code names directly (a class/module/component). altLabel = the exact code
    symbols that ARE it.
  - "aspect": a cross-cutting concern with no single home symbol (e.g. error-handling, concurrency,
    authentication). For these, give a precise `definition` (scope note) instead of relying on names.

Rules:
- altLabel values must be drawn ONLY from the mined vocabulary you were given. Do not invent symbols.
- Prefer concepts an engineer would actually query ("where is X?"). Drop one-off noise.
- `broader` (optional) is the prefLabel-key of a parent concept, for hierarchy.
- Output ONLY JSON, no fences:
  {"concepts":[{"key":"kebab-name","prefLabel":"...","type":"entity|aspect",
    "altLabel":["..."],"definition":"one line","broader":"parent-key-or-empty"}]}"""


def to_toml(concepts):
    out = ["# DRAFT ontology — LLM-proposed, NOT curated. Review every entry before use.",
           "# Trust the membership; re-check the hierarchy (LLMs propose relations poorly).\n"]
    for c in concepts:
        key = c.get("key") or normalize(c.get("prefLabel", "concept"))
        out.append(f"[concepts.{key}]")
        out.append(f'type = "{c.get("type","entity")}"')
        out.append(f'prefLabel = {json.dumps(c.get("prefLabel",""))}')
        if c.get("definition"):
            out.append(f'definition = {json.dumps(c["definition"])}')
        if c.get("type") == "aspect":
            out.append(f'recall_keywords = {json.dumps(c.get("altLabel",[]) or [c.get("prefLabel","").lower()])}')
        else:
            out.append(f'altLabel = {json.dumps(c.get("altLabel",[]))}')
        if c.get("broader"):
            out.append(f'broader = [{json.dumps(c["broader"])}]')
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="call the LLM and write a draft (default: dry-run)")
    ap.add_argument("--top-tokens", type=int, default=45)
    ap.add_argument("--top-segs", type=int, default=20)
    ap.add_argument("--top-anchored", type=int, default=30)
    args = ap.parse_args()

    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("Set CK_PORTFOLIO to the portfolio root.")
    CK = P / ".context-kernel"
    state = json.loads((CK / "graph/state.json").read_text())
    tokf, segf, anchored = mine(state)

    toks = [t for t, _ in tokf.most_common(args.top_tokens)]
    segs = [s for s, _ in segf.most_common(args.top_segs)]
    anch = anchored[:args.top_anchored]
    print("mined identifier tokens:", toks)
    print("\nmined path segments:", segs)
    print("\ndoc-anchored code symbols (strong entity-concepts):", anch)

    if not args.execute:
        print("\n[dry-run] no LLM called. Re-run with --execute to nominate a draft ontology.")
        return

    cfg = load(CK / "config.toml").ingester
    api_key = os.environ.get(cfg.summarizer_api_key_env)
    if not api_key:
        sys.exit(f"Missing API key: set ${cfg.summarizer_api_key_env}")
    client = build_client(timeout=120.0)
    user = (f"Mined identifier tokens (freq-ranked): {toks}\n\n"
            f"Mined module/directory names: {segs}\n\n"
            f"Code symbols documentation references (strong entity candidates): {anch}\n\n"
            f"Propose the draft ontology now.")
    raw = _chat(client, cfg.summarizer_endpoint, cfg.summarizer_model, api_key, _SYSTEM, user)
    t = raw.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        concepts = json.loads(t.strip()).get("concepts", [])
    except json.JSONDecodeError:
        sys.exit("LLM returned unparseable JSON; re-run (temperature is low but not zero).")

    outdir = CK / "spike-results"; outdir.mkdir(parents=True, exist_ok=True)
    draft = outdir / "ontology.draft.toml"
    draft.write_text(to_toml(concepts))
    n_e = sum(1 for c in concepts if c.get("type") == "entity")
    n_a = sum(1 for c in concepts if c.get("type") == "aspect")
    print(f"\nproposed {len(concepts)} concepts ({n_e} entity, {n_a} aspect)")
    print(f"wrote {draft} (DRAFT — curate, then copy into ontology.toml; do not commit)")


if __name__ == "__main__":
    main()
