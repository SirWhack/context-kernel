"""Drop diagnostics — the standing denominator for relationship resolution.

When the EntityResolver (ADR-0017) can't resolve a relationship endpoint, it drops the edge.
Counting drops is meaningless on its own: most are *correct* (an ambiguous `main`, an external
library, a directory), and only a few are *recoverable* (the endpoint names a real, unique
entity in a spelling the resolver missed). This module classifies the drop population so we
never again mistake drop-count for lost data — the mistake that sent ADR-0027 chasing a
phantom (0/412 bound; 95% were correct drops). Pure function; called by the resolver, written
to `.context-kernel/diagnostics/drops.md` each ingest.

Buckets — CORRECT (expected, no action): `ambiguous`, `external`, `directory`, `prose`,
`no_referent`. RECOVERABLE (a real gap worth a deterministic fix): `recoverable`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from context_kernel.source_kinds import CODE_EXT

CORRECT_BUCKETS = ("ambiguous", "external", "directory", "prose", "no_referent")
RECOVERABLE_BUCKET = "recoverable"

# `Name (kind, file)` — the ADR-0016 code-context display line, echoed verbatim by the extractor.
_CTX_ECHO = re.compile(r"^(.+?) \((?:module|class|function|interface), .+\)$")


def candidate_bare(phrase: str) -> str:
    """Best-effort canonical name a drop phrase is *trying* to name — strips the two formats the
    doc extractor echoes: `Name (kind, file)` → `Name`, and `path.py:Symbol` → `Symbol`."""
    p = phrase.strip()
    m = _CTX_ECHO.match(p)
    if m:
        return m.group(1).strip()
    if ":" in p:
        head, _, tail = p.partition(":")
        if head.strip().endswith(CODE_EXT) and tail and not tail[0].isdigit():
            return tail.strip()
    return p


def _bucket(
    phrase: str,
    *,
    code_name_count: dict[str, int],
    ambiguous_bases: set[str],
    file_paths: set[str],
    stoplist: frozenset[str],
    normalize: Callable[[str], str],
) -> str:
    p = phrase.strip()
    cand = candidate_bare(p)
    # A path (or path:line) that names a real ingested file → recoverable (should resolve).
    head = p.partition(":")[0]
    if head.endswith(CODE_EXT) and head.lstrip("./") in file_paths:
        return "recoverable"
    # Directory target (`src/tools/analysis`) — a bare path with no file, no echo/symbol stripped.
    if cand == p and "/" in p and ":" not in p and not p.endswith(CODE_EXT):
        return "directory"
    nb = normalize(cand)
    if cand in stoplist or nb in stoplist or nb in ambiguous_bases:
        return "ambiguous"
    n = code_name_count.get(cand, 0)
    if n == 1:
        return "recoverable"          # uniquely names a real entity but didn't resolve — a gap
    if n > 1:
        return "ambiguous"            # names several real entities — correct to drop, never guess
    # Dotted, last segment unknown → external library reference (`asyncio.create_task`).
    if "." in cand and code_name_count.get(cand.rsplit(".", 1)[-1], 0) == 0:
        return "external"
    if len(p.split()) >= 3:
        return "prose"                # a descriptive phrase, not a symbol
    return "no_referent"              # short name with no node — renamed/removed/hallucinated


@dataclass
class DropReport:
    total: int = 0
    buckets: dict[str, int] = field(default_factory=dict)
    recoverable: list[dict] = field(default_factory=list)   # sample: {phrase, candidate, kind}

    @property
    def recoverable_count(self) -> int:
        return self.buckets.get(RECOVERABLE_BUCKET, 0)

    @property
    def correct_count(self) -> int:
        return sum(self.buckets.get(b, 0) for b in CORRECT_BUCKETS)


def classify_drops(
    drops: list[tuple[str, str]],          # (unresolved endpoint phrase, edge kind)
    *,
    code_name_count: dict[str, int],
    ambiguous_bases: set[str],
    file_paths: set[str],
    stoplist: frozenset[str],
    normalize: Callable[[str], str],
    sample_cap: int = 60,
) -> DropReport:
    buckets: Counter = Counter()
    recoverable: list[dict] = []
    for phrase, kind in drops:
        b = _bucket(phrase, code_name_count=code_name_count, ambiguous_bases=ambiguous_bases,
                    file_paths=file_paths, stoplist=stoplist, normalize=normalize)
        buckets[b] += 1
        if b == RECOVERABLE_BUCKET and len(recoverable) < sample_cap:
            recoverable.append({"phrase": phrase, "candidate": candidate_bare(phrase), "kind": kind})
    return DropReport(total=len(drops), buckets=dict(buckets), recoverable=recoverable)


def format_report(report: DropReport) -> str:
    """Human-readable markdown for `.context-kernel/diagnostics/drops.md`."""
    lines = [
        "# Relationship-drop diagnostics",
        "",
        f"- **Total dropped endpoints:** {report.total}",
        f"- **Correct drops** (expected — ambiguous / external / directory / prose / no-referent): "
        f"{report.correct_count}",
        f"- **Recoverable** (names a real unique entity but didn't resolve — worth a fix): "
        f"**{report.recoverable_count}**",
        "",
        "## By bucket",
        "",
        "| bucket | count | class |",
        "|---|---:|---|",
    ]
    order = [RECOVERABLE_BUCKET, *CORRECT_BUCKETS]
    for b in order:
        c = report.buckets.get(b, 0)
        if not c:
            continue
        cls = "RECOVERABLE" if b == RECOVERABLE_BUCKET else "correct"
        lines.append(f"| {b} | {c} | {cls} |")
    if report.recoverable:
        lines += ["", "## Recoverable sample (fix these)", "", "| kind | phrase | → candidate |", "|---|---|---|"]
        for r in report.recoverable:
            lines.append(f"| {r['kind']} | `{r['phrase']}` | `{r['candidate']}` |")
    else:
        lines += ["", "_No recoverable drops — the resolver is binding everything it should._"]
    return "\n".join(lines) + "\n"
