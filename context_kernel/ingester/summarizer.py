"""Summarizer Parnas-secret — hides which LLM produces entity-extraction summaries.

See ARCHITECTURE.md §2.2, ADR-0013 for the markdown entity taxonomy.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from context_kernel.ingester.handlers import RawEntity, RawRelationship

log = logging.getLogger(__name__)

# Entity kinds the LLM is instructed to extract from documentation.
# See ADR-0013 for rationale on why these 8 and what was cut.
ENTITY_KINDS = frozenset({
    "decision",
    "constraint",
    "invariant",
    "trade-off",
    "risk",
    "workflow",
    "interface",
    "open-question",
})

# Relationship kinds for doc-to-doc and doc-to-code edges.
RELATIONSHIP_KINDS = frozenset({
    "implements",
    "governed-by",
    "motivates",
    "supersedes",
    "addresses",
})

_SYSTEM_PROMPT = """\
You are an entity extractor for a software documentation knowledge graph.
Given a chunk of technical documentation, extract entities and relationships.

## Entity kinds (use ONLY these)
- decision: A resolved choice with rationale. Includes non-goals (decisions NOT to do something).
- constraint: An externally imposed boundary (platform, resource, timeline). Not chosen — inherited.
- invariant: A property the system must always maintain. Internally chosen.
- trade-off: An explicit tension between competing qualities.
- risk: An identified threat to success, with potential impact.
- workflow: A sequenced process or pipeline.
- interface: A contract boundary — API surface, protocol, schema, integration point.
- open-question: An unresolved issue requiring future decision.

## Relationship kinds (use ONLY these)
- implements: Code entity realizes a doc entity (e.g., class implements a decision).
- governed-by: Code or design is constrained by a rule (invariant, constraint).
- motivates: One entity is the reason another exists.
- supersedes: One decision replaces another.
- addresses: A decision resolves an open question.

## Rules
- Extract 1-8 entities per chunk. Prefer fewer, higher-quality entities over many vague ones.
- Entity names should be specific and reusable (e.g., "pre-commit hook regeneration" not "the approach").
- If the text references code constructs (class names, function names, module names), emit \
relationships linking the doc entity to the code construct name.
- For relationships, source_name and target_name must be entity names from this chunk or \
well-known code identifiers referenced in the text.

## Output format
Return ONLY valid JSON, no markdown fences, no commentary:
{"entities": [{"name": "...", "kind": "...", "description": "..."}], \
"relationships": [{"source_name": "...", "target_name": "...", "kind": "...", "description": "..."}]}

If the chunk contains no extractable entities, return: {"entities": [], "relationships": []}
"""


class Summarizer(Protocol):
    """Extract entities and relationships from a source-file chunk."""

    def summarize(self, text: str) -> tuple[list[RawEntity], list[RawRelationship]]:
        """Best-effort extraction. Quality is not guaranteed (§2.2 Does not own)."""
        ...


def _parse_llm_response(raw: str) -> tuple[list[RawEntity], list[RawRelationship]]:
    """Parse JSON from LLM output into Raw types. Tolerates common LLM quirks."""
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else 3
        text = text[first_nl + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Summarizer returned invalid JSON, skipping chunk")
        return [], []

    entities: list[RawEntity] = []
    for e in data.get("entities", []):
        name = e.get("name", "").strip()
        kind = e.get("kind", "").strip().lower()
        desc = e.get("description", "").strip()
        if not name or not kind:
            continue
        if kind not in ENTITY_KINDS:
            log.debug("Unknown entity kind %r from LLM, accepting anyway", kind)
        entities.append(RawEntity(name=name, kind=kind, description=desc))

    relationships: list[RawRelationship] = []
    for r in data.get("relationships", []):
        src = r.get("source_name", "").strip()
        tgt = r.get("target_name", "").strip()
        kind = r.get("kind", "").strip().lower()
        desc = r.get("description", "").strip()
        if not src or not tgt or not kind:
            continue
        relationships.append(RawRelationship(source_name=src, target_name=tgt, kind=kind, description=desc))

    return entities, relationships


class LLMSummarizer:
    """Concrete Summarizer that calls a local OpenAI-compatible LLM endpoint."""

    def __init__(self, endpoint: str, model: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model

    def summarize(self, text: str) -> tuple[list[RawEntity], list[RawRelationship]]:
        import httpx

        try:
            resp = httpx.post(
                f"{self._endpoint}/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception:
            log.warning("Summarizer LLM call failed for chunk (len=%d), skipping", len(text), exc_info=True)
            return [], []

        return _parse_llm_response(content)
