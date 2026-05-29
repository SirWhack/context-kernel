"""Evidence-span oracle — ADR-0018's single source of "what counts as this concept in source".

One function, three consumers:
  - concept_classify.py  — emits a CodeSpan per confirmed aspect participant (the evidence leaves).
  - concept_materialize.py — renders those leaves (`file:line — primitive`), re-deriving the line.
  - h2_eval.py           — scores aspect precision against the same matcher.

A span is content, not position: `{pattern, snippet}` — the matched coordination primitive and its
source line text. The LINE NUMBER is never stored; it is re-derived from current source at render
time by `locate()`, so it cannot go stale (ADR-0018 decision-points 3 & 4).

`precision_patterns(spec)` picks the tight "what truly counts" oracle if the concept defines one,
else falls back to the broad `structural_patterns` recall net — they differ on purpose: the recall
net casts wide (e.g. bare `import asyncio`) to gather candidates; the precision oracle keeps only
real primitives (Lock/Semaphore/wait_for/…). Generic, no corpus names.
"""
import re


def precision_patterns(spec):
    """The strict evidence oracle for a concept spec; falls back to the recall net."""
    return spec.get("precision_patterns") or spec.get("structural_patterns") or []


def find_spans(text, patterns, max_spans=8):
    """Lines of CODE in `text` matching any precision pattern → [{pattern, snippet}] (content, no line).

    Evidence must be code, not prose about code: lines inside a triple-quoted docstring and lines
    that are comments (`#`/`//`) are skipped — the primitive name appearing in a docstring or comment
    is a mention, not a coordination site. De-duplicated by snippet so one line isn't emitted twice.
    (Approximate, regex-level — good enough for a single-file scan; AST would be exact.)
    """
    regs = [(p, re.compile(p)) for p in patterns]
    spans, seen = [], set()
    in_doc = None                                   # the triple-quote delimiter we're inside, or None
    for ln in text.splitlines():
        s = ln.strip()
        if in_doc:                                  # inside a docstring → skip until it closes
            if in_doc in s:
                in_doc = None
            continue
        opener = next((d for d in ('"""', "'''") if s.count(d) == 1), None)
        if opener:                                  # docstring opens here (and doesn't close same line)
            in_doc = opener
            continue
        if not s or s.startswith(("#", "//", '"""', "'''")) or s in seen:
            continue   # comment, or a one-line docstring (`"""…"""`) — a mention, not code
        for pat, rg in regs:
            if rg.search(ln):
                spans.append({"pattern": pat, "snippet": s[:120]})
                seen.add(s)
                break
        if len(spans) >= max_spans:
            break
    return spans


def locate(text, span):
    """Re-derive a span's CURRENT line number in `text` (1-based); None if it no longer appears.

    Tries the exact snippet first (cheap, robust to line drift), then the pattern (robust to a
    cosmetic edit of the line). Returning None is meaningful: the primitive was removed, so the
    evidence — and the concept membership it justified — should decay (ADR-0018 decision-point 5).
    """
    snippet, pat = span.get("snippet", ""), span.get("pattern", "")
    lines = text.splitlines()
    if snippet:
        for i, ln in enumerate(lines):
            if ln.strip()[:120] == snippet:
                return i + 1
    if pat:
        rg = re.compile(pat)
        for i, ln in enumerate(lines):
            if rg.search(ln):
                return i + 1
    return None
