"""Extract code-level gotchas for ENTITY-concepts from their anchor source.

Aspect-concepts get gotchas from the source-evidence judge (concept_classify.py). Entity-concepts
are alias-grounded and skip the judge, so their hubs lacked the code-level landmines grep surfaces
(H2 Q3: the `think`-exemption, a legacy duplicate). This reads each entity-concept's implementation
file(s) and asks the LLM for ≤3 such gotchas. Reads the graph; does not mutate it.

Usage:  CK_PORTFOLIO=/path python scripts/concept_gotchas.py            # dry-run: list anchors
        CK_PORTFOLIO=/path python scripts/concept_gotchas.py --execute  # calls the LLM
Writes  $CK_PORTFOLIO/.context-kernel/spike-results/entity_gotchas.json  (local; do not commit)
Auth    api key from env named by ingester.summarizer_api_key_env (e.g. FOUNDRY_KEY)

Generic / CK_PORTFOLIO-driven, no corpus names.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from context_kernel.config_store import load
from context_kernel.ingester._http import build_client, post_with_retry
from context_kernel.ingester.entity_resolver import normalize

import tomllib

PY = (".py",); JS = (".ts", ".tsx", ".js", ".jsx")
def _ext(s): return s[s.rfind("."):] if "." in s else ""
def _is_code(e): return any(_ext(s) in PY + JS for s in e.get("sources", []) or [])

_SYSTEM = """\
You extract code-level GOTCHAS — the risks/constraints/landmines a developer must know BEFORE
changing this code. Good gotchas: a duplicate/legacy implementation to NOT edit, a special-case
exemption, an ordering/cancellation requirement, an invariant that must hold, a "change X not Y".
Bad gotchas: restating what the code does. Output ONLY JSON, no prose."""


def _chat(client, endpoint, model, api_key, system, user, max_tokens=1024):
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


def _parse(raw):
    t = raw.strip()
    if t.startswith("```"):
        t = t[t.index("\n") + 1:] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    try:
        return [g for g in json.loads(t.strip()).get("gotchas", []) if isinstance(g, str) and g.strip()]
    except json.JSONDecodeError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="call the LLM (default: dry-run)")
    ap.add_argument("--max-chars", type=int, default=8000, help="source chars per concept sent to the LLM")
    args = ap.parse_args()

    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("Set CK_PORTFOLIO to the portfolio root.")
    CK = P / ".context-kernel"
    state = json.loads((CK / "graph/state.json").read_text())
    onto = tomllib.loads((CK / "ontology.toml").read_text())["concepts"]
    ents = state["entities"]

    def ground(spec):
        want = {normalize(a) for a in (spec.get("altLabel") or []) + [spec.get("prefLabel", "")] if a}
        return [e for e in ents if _is_code(e)
                and any(normalize(n) in want for n in [e["name"], *(e.get("aliases") or [])])]

    targets = {k: s for k, s in onto.items() if s.get("type", "entity") == "entity"}
    plan = {}
    for key, spec in targets.items():
        files = sorted({s for e in ground(spec) for s in e.get("sources", []) or [] if _ext(s) in PY + JS})
        plan[key] = files
        print(f"  {key:20} anchors: {[f.split('/')[-1] for f in files] or '(none grounded)'}")

    if not args.execute:
        print("\n[dry-run] no LLM called. Re-run with --execute to extract gotchas.")
        return

    cfg = load(CK / "config.toml").ingester
    api_key = os.environ.get(cfg.summarizer_api_key_env)
    if not api_key:
        sys.exit(f"Missing API key: set ${cfg.summarizer_api_key_env}")
    client = build_client(timeout=120.0)
    outdir = CK / "spike-results"; cachedir = outdir / "cache"; cachedir.mkdir(parents=True, exist_ok=True)

    out = {}
    for key, files in plan.items():
        if not files:
            continue
        blob, used = [], 0
        for f in files:
            try:
                txt = (P / f).read_text(errors="ignore")
            except OSError:
                continue
            chunk = txt[: max(0, args.max_chars - used)]
            blob.append(f"# {f}\n{chunk}")
            used += len(chunk)
            if used >= args.max_chars:
                break
        source = "\n\n".join(blob)
        ckey = hashlib.sha256((cfg.summarizer_model + "|" + key + "|" + source).encode()).hexdigest()
        cpath = cachedir / f"gotcha_{ckey}.json"
        if cpath.exists():
            gotchas = json.loads(cpath.read_text())
        else:
            spec = targets[key]
            user = (f"Concept: {spec.get('prefLabel', key)}\nDefinition: {spec.get('definition','')}\n\n"
                    f"Implementation source:\n{source}\n\n"
                    f'Return ONLY {{"gotchas":["<=15 words each, max 3; [] if none"]}}.')
            gotchas = _parse(_chat(client, cfg.summarizer_endpoint, cfg.summarizer_model, api_key, _SYSTEM, user))
            cpath.write_text(json.dumps(gotchas))
        out[key] = gotchas
        print(f"\n{key}: {len(gotchas)} gotchas")
        for g in gotchas:
            print(f"    - {g}")

    (outdir / "entity_gotchas.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {outdir/'entity_gotchas.json'} (local only — do not commit)")


if __name__ == "__main__":
    main()
