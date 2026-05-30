"""H2 eval — audit a Claude Code orientation session against ground truth.

Formalizes the by-hand audit we ran each H2 round (cost from the transcript; aspect precision by
counting real coordination primitives in each claimed file). Runs as an eval over one or more
Claude Code session transcripts (`.jsonl`) and scores each arm on three deterministic axes:

  1. COST       — tool calls (by type), failed calls (`is_error` tool_results), duplicate reads,
                  fresh tokens (in+out). Straight from the transcript.
  2. HALLUCINATION — every file path the final answer claims is resolved under CK_PORTFOLIO;
                  paths that resolve to nothing are flagged (the r1 `tab/responder.py` failure mode).
  3. ASPECT PRECISION — for each aspect-concept in the ontology (type=aspect, has
                  `structural_patterns`), find that concept's question section in the answer, pull the
                  files it claims, and count how many actually contain a coordination primitive.
                  precision = files-with-primitive / files-claimed. The 0-primitive files are the
                  false positives (the Q4 `planner`/`retry`/`turn_log_store` failure mode). Scored
                  against a concept's `precision_patterns` (tight "what truly counts" oracle) if
                  defined, else its broad `structural_patterns` recall net — they differ on purpose:
                  a recall net casts wide (e.g. bare `import asyncio`) to gather candidates, a
                  precision oracle keeps only real primitives (Lock/Semaphore/wait_for/…). This is
                  the SAME ground-truth rule the materializer's recall used — honest, not circular:
                  it measures "did the agent claim coordination where a primitive actually exists."

Optional recall: pass `--gold gold.toml` with `[Q1] files=[...]` sections to also score recall
(gold items found / gold items) per question — gold is corpus-specific so it stays local.

Usage:
  CK_PORTFOLIO=/path/to/project python scripts/h2_eval.py SESSION_A.jsonl SESSION_B.jsonl
  CK_PORTFOLIO=/path        python scripts/h2_eval.py --dir ~/.claude/projects/<proj> --last 2
  CK_PORTFOLIO=/path        python scripts/h2_eval.py s1.jsonl s2.jsonl --gold gold.toml

Reads   $CK_PORTFOLIO/.context-kernel/ontology.toml (for aspect structural_patterns)
        the transcript(s) named on the CLI (or newest N in --dir)
Writes  nothing — prints a per-session report + a side-by-side compare table.

Generic / CK_PORTFOLIO-driven, no corpus names. Transcripts + gold sets stay local.
"""
import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from concept_spans import precision_patterns, find_spans   # ADR-0018: one oracle, three consumers

# File types an answer may cite. Code stays first; infra/config added so foreign corpora
# (Dockerfiles, compose/yaml, shell, json/toml configs) are scored, not silently dropped.
# The `(?![A-Za-z0-9])` boundary stops `.js` from matching inside `.json` (the prefix bug).
_EXTS = (r"py|pyi|tsx|ts|jsx|js|mjs|cjs|md|mdx|ya?ml|toml|json|jsonc"
         r"|sh|bash|cfg|conf|ini|env|lock|sql|rs|go")
_NAMES = r"Dockerfile|Containerfile|Makefile"
PATH_RE = re.compile(
    r"`?("
    r"(?:[\w.\-]+/)*[\w.\-]+\.(?:" + _EXTS + r")(?![A-Za-z0-9])"
    r"|(?:[\w.\-]+/)*(?:" + _NAMES + r")(?![A-Za-z0-9.])"
    r")`?")
EXT_RE = re.compile(r"\.(?:" + _EXTS + r")$|(?:^|/)(?:" + _NAMES + r")$")
META_FILES = {"claude.md", "agents.md", "readme.md"}
SCORECARD_RE = re.compile(r"^\s*#{0,4}\s*scorecard\b|^\s*\|\s*Q\b", re.I)
# a question header is EITHER a markdown header carrying a number ("## 4. Concurrency", "## Q4 — X")
# OR a Q-style line ("Q1 — Turn Panel", "**Q1**"). Plain body enumeration ("1. read the index") is
# NOT a header — it lacks both the `#` prefix and the `Q`.
QHEAD_RE = re.compile(
    r"^\s*#{1,4}\s*(?:Q\s*)?(\d+)\s*[.)\-—:]*\s*(.*\S)?\s*$"    # markdown header w/ number, title optional
    r"|^\s*\**\s*Q\s*(\d+)\b\s*[.)\-—:]*\s*(.*\S)?\s*$",         # Q-style line, optionally bold
    re.I)


# ── transcript parsing ───────────────────────────────────────────────────────
def parse_transcript(path):
    arm, final = "?", ""
    tools = []                 # (name, arg)
    by_id = {}                 # tool_use id -> name
    failed = 0
    usage = {"in": 0, "out": 0, "cache_r": 0, "cache_w": 0}
    first_user = None
    for line in Path(path).read_text().splitlines():
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = o.get("message", {})
        content = m.get("content")
        role = m.get("role") or o.get("type")
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            blocks = content
        else:
            blocks = []
        if role == "user" and first_user is None:
            txt = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            if txt.strip() and not txt.lstrip().startswith("<"):
                first_user = txt
        if o.get("type") == "assistant":
            u = m.get("usage", {})
            usage["in"] += u.get("input_tokens", 0); usage["out"] += u.get("output_tokens", 0)
            usage["cache_r"] += u.get("cache_read_input_tokens", 0); usage["cache_w"] += u.get("cache_creation_input_tokens", 0)
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                name, inp = b.get("name", "?"), b.get("input", {})
                by_id[b.get("id")] = name
                if name == "Read":
                    arg = inp.get("file_path", "")
                elif name in ("Bash",):
                    arg = inp.get("command", "")[:80]
                elif name in ("Grep", "Glob"):
                    arg = f"{inp.get('pattern','')} {inp.get('path','')}".strip()
                else:
                    arg = json.dumps(inp)[:80]
                tools.append((name, arg))
            elif b.get("type") == "tool_result":
                if b.get("is_error"):
                    failed += 1
            elif b.get("type") == "text" and o.get("type") == "assistant":
                final = b.get("text", "")
    if first_user:
        low = first_user.lower()
        if "arm a" in low:                                 # explicit arm label wins
            arm = "kernel"
        elif "arm b" in low:
            arm = "grep"
        elif "concept kernel" in low or "context kernel" in low or "concept hub" in low:
            arm = "kernel"                                  # kernel signal before generic "grep"
        elif "baseline" in low or "grep" in low or "ripgrep" in low:
            arm = "grep"
    reads = [a for n, a in tools if n == "Read"]
    dup_reads = len(reads) - len(set(reads))
    return {"path": str(path), "arm": arm, "tools": tools, "failed": failed,
            "dup_reads": dup_reads, "usage": usage, "final": final}


# ── ground-truth helpers ─────────────────────────────────────────────────────
def resolve(root, rel):
    """Resolve a claimed path under root; bare basenames are searched. None if nothing matches."""
    rel = rel.strip("`").lstrip("./")
    p = root / rel
    if p.exists():
        return p
    if "/" in rel:                                  # dir-qualified but missing → likely hallucination
        hits = list(root.rglob(rel.split("/")[-1]))
        # only accept if the FULL suffix matches some real path
        for h in hits:
            if str(h).replace("\\", "/").endswith(rel):
                return h
        return None
    hits = [h for h in root.rglob(rel) if h.is_file()]
    return hits[0] if hits else None


def count_primitives(text, patterns):
    return len(find_spans(text, patterns, max_spans=99))   # same oracle the pipeline emits from


def strip_scorecard(final):
    """Drop the trailing scorecard table + footer — it lists every file from every question,
    which otherwise bleeds into the last question's section."""
    out = []
    for ln in final.splitlines():
        if SCORECARD_RE.match(ln):
            break
        out.append(ln)
    return "\n".join(out)


def section_split(final):
    """Split the answer into {qnum: (title, body)} by Q-headers (scorecard stripped first)."""
    final = strip_scorecard(final)
    lines = final.splitlines()
    sections, cur, buf, title = {}, None, [], ""
    for ln in lines:
        m = QHEAD_RE.match(ln)
        if m:
            if cur is not None:
                sections[cur] = (title, "\n".join(buf))
            cur = int(m.group(1) or m.group(3))
            title = (m.group(2) or m.group(4) or "").strip(" —-:.")
            buf = []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        sections[cur] = (title, "\n".join(buf))
    return sections


# a path on a line the agent explicitly hedged ("⚠ unverified lead", "not a fact") is NOT a claim —
# scoring it as one penalizes the agent for correctly demoting it (the hub's flagged section working).
NONCLAIM_RE = re.compile(r"⚠|unverified|not a fact|treat as a? lead|treat as leads|flagged", re.I)


def claim_text(text):
    return "\n".join(ln for ln in text.splitlines() if not NONCLAIM_RE.search(ln))


def extract_paths(text):
    out = set()
    for m in PATH_RE.finditer(text):
        c = m.group(1)
        segs = c.split("/")
        if any(EXT_RE.search(s) for s in segs[:-1]):       # "CLAUDE.md/AGENTS.md" — a file as a dir
            continue
        if segs[-1].lower() in META_FILES:                 # harness preamble, not an answer claim
            continue
        out.add(c)
    return sorted(out)


# ── audits ───────────────────────────────────────────────────────────────────
def audit_hallucination(parsed, root):
    claimed = extract_paths(parsed["final"])
    missing = [c for c in claimed if resolve(root, c) is None]
    return claimed, missing


def audit_aspect_precision(parsed, root, aspects):
    """For each aspect concept, find its Q-section, score precision over claimed code files."""
    sections = section_split(parsed["final"])
    out = {}
    for key, spec in aspects.items():
        # precision oracle ≠ recall net: structural_patterns are broad (gather candidates, e.g.
        # bare `import asyncio`); precision_patterns, if present, are the tighter "what actually
        # counts as this concept" set used to score whether a claimed file truly participates.
        pats = precision_patterns(spec)
        pref = spec.get("prefLabel", key).lower()
        kws = [pref] + [k.lower() for k in spec.get("recall_keywords", [])]
        # match the section whose title mentions the concept
        sec = next((body for _, (title, body) in sections.items()
                    if any(k in title.lower() for k in kws)), None)
        if sec is None:
            out[key] = None
            continue
        code = [c for c in extract_paths(claim_text(sec)) if c.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))]
        rows, hits = [], 0
        for c in code:
            f = resolve(root, c)
            n = count_primitives(f.read_text(errors="ignore"), pats) if f else -1
            rows.append((c, n))
            if n > 0:
                hits += 1
        scored = [r for r in rows if r[1] >= 0]
        prec = hits / len(scored) if scored else 0.0
        out[key] = {"claimed": len(code), "scored": len(scored), "hits": hits,
                    "precision": prec, "false_pos": [c for c, n in rows if n == 0],
                    "unresolved": [c for c, n in rows if n < 0]}
    return out


def audit_recall(parsed, gold):
    sections = section_split(parsed["final"])
    out = {}
    for q, items in gold.items():
        body = sections.get(q, ("", ""))[1]
        claimed = set(extract_paths(body)) | {p for p in extract_paths(body)}
        found = [g for g in items if any(g in c or c.endswith(g) for c in claimed)]
        out[q] = {"found": len(found), "gold": len(items), "missed": [g for g in items if g not in found]}
    return out


def audit_grounding(parsed, gold, root):
    """Gold files the arm actually OPENED (a Read tool call), not merely named in the prose.
    This is the memory-proof axis: on a public/memorized repo, an arm can recall the right
    paths without retrieving — grounding only credits files whose contents it actually read."""
    opened = [a for n, a in parsed["tools"] if n == "Read"]
    out = {}
    for q, items in gold.items():
        hit = [g for g in items if any(o.endswith(g) or o.endswith("/" + g) for o in opened)]
        out[q] = {"opened": len(hit), "gold": len(items),
                  "missed": [g for g in items if g not in hit]}
    return out


# ── reporting ────────────────────────────────────────────────────────────────
def report(parsed, root, aspects, gold):
    u = parsed["usage"]; fresh = u["in"] + u["out"]
    tcount = len(parsed["tools"])
    print(f"\n{'='*72}\n  {parsed['arm'].upper():7} {Path(parsed['path']).name}")
    print(f"  COST  tool_calls={tcount}  failed={parsed['failed']}  dup_reads={parsed['dup_reads']}  "
          f"fresh_tokens={fresh}  (in={u['in']} out={u['out']} cache_r={u['cache_r']})")
    claimed, missing = audit_hallucination(parsed, root)
    print(f"  PATHS claimed={len(claimed)}  resolved={len(claimed)-len(missing)}  "
          f"MISSING={missing if missing else '0 ✓'}")
    prec = audit_aspect_precision(parsed, root, aspects)
    for key, r in prec.items():
        if r is None:
            print(f"  ASPECT {key}: (no matching question section)")
        else:
            print(f"  ASPECT {key}: precision={r['precision']:.0%} "
                  f"({r['hits']}/{r['scored']} claimed files have a primitive)"
                  + (f"  false_pos={r['false_pos']}" if r['false_pos'] else "")
                  + (f"  unresolved={r['unresolved']}" if r['unresolved'] else ""))
    rec = audit_recall(parsed, gold) if gold else {}
    for q, r in sorted(rec.items()):
        print(f"  RECALL Q{q}: {r['found']}/{r['gold']}"
              + (f"  missed={r['missed']}" if r['missed'] else " ✓"))
    grd = audit_grounding(parsed, gold, root) if gold else {}
    for q, r in sorted(grd.items()):
        print(f"  GROUND Q{q}: {r['opened']}/{r['gold']} opened"
              + (f"  not-opened={r['missed']}" if r['missed'] else " ✓"))
    g_open = sum(r["opened"] for r in grd.values())
    g_tot = sum(r["gold"] for r in grd.values())
    r_found = sum(r["found"] for r in rec.values())
    return {"arm": parsed["arm"], "calls": tcount, "failed": parsed["failed"],
            "dup": parsed["dup_reads"], "fresh": fresh, "missing": len(missing),
            "precision": prec, "recall": rec,
            "grounded": (g_open, g_tot), "recalled": (r_found, g_tot)}


def compare(rows):
    print(f"\n{'='*72}\n  COMPARE")
    hdr = (f"  {'arm':8} {'calls':>5} {'failed':>6} {'dup':>4} {'fresh_tok':>9} {'halluc':>6} "
           f"{'grounded':>9} {'recalled':>9}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        g = f"{r['grounded'][0]}/{r['grounded'][1]}"
        rc = f"{r['recalled'][0]}/{r['recalled'][1]}"
        print(f"  {r['arm']:8} {r['calls']:>5} {r['failed']:>6} {r['dup']:>4} {r['fresh']:>9} "
              f"{r['missing']:>6} {g:>9} {rc:>9}")
    # aspect precision side by side
    keys = sorted({k for r in rows for k in r["precision"]})
    for k in keys:
        cells = []
        for r in rows:
            pr = r["precision"].get(k)
            cells.append(f"{r['arm']}={pr['precision']:.0%}" if pr else f"{r['arm']}=n/a")
        print(f"  aspect {k}: " + "  ".join(cells))


def main():
    ap = argparse.ArgumentParser(description="Eval Claude Code orientation sessions against ground truth.")
    ap.add_argument("transcripts", nargs="*", help="session .jsonl files")
    ap.add_argument("--dir", help="a Claude project dir; takes the newest --last sessions")
    ap.add_argument("--last", type=int, default=2, help="with --dir, how many newest sessions")
    ap.add_argument("--gold", help="optional gold.toml with [Q1] files=[...] sections for recall")
    args = ap.parse_args()

    P = Path(os.environ.get("CK_PORTFOLIO", "")).expanduser()
    if not P.exists():
        sys.exit("Set CK_PORTFOLIO to the portfolio root.")
    onto_path = P / ".context-kernel/ontology.toml"
    if onto_path.exists():
        onto = tomllib.loads(onto_path.read_text())["concepts"]
        aspects = {k: s for k, s in onto.items()
                   if s.get("type") == "aspect" and s.get("structural_patterns")}
    else:
        aspects = {}  # foreign repos have no ontology — cost + hallucination + recall still score

    paths = list(args.transcripts)
    if args.dir:
        files = sorted(Path(args.dir).expanduser().glob("*.jsonl"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        paths += [str(f) for f in files[:args.last]]
    if not paths:
        sys.exit("Pass transcript .jsonl files, or --dir with --last N.")

    gold = {}
    if args.gold:
        g = tomllib.loads(Path(args.gold).expanduser().read_text())
        gold = {int(re.sub(r"\D", "", q)): v.get("files", []) for q, v in g.items()}

    print(f"corpus root: {P}\naspect concepts audited: {list(aspects)}")
    rows = [report(parse_transcript(p), P, aspects, gold) for p in paths]
    if len(rows) > 1:
        compare(rows)


if __name__ == "__main__":
    main()
