"""Summarizer Parnas-secret — hides which LLM produces entity-extraction summaries.

See ARCHITECTURE.md §2.2, ADR-0013 for the markdown entity taxonomy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from context_kernel.ingester._http import build_client, post_with_retry
from context_kernel.ingester.handlers import RawEntity, RawRelationship

if TYPE_CHECKING:
    from context_kernel.ontology import Ontology
    from context_kernel.types import LLMMetrics

log = logging.getLogger(__name__)

_CACHE_VERSION = "v5"  # bumped: prompt + kinds now derive from ontology.yaml (ADR-0024)

# Default kind tables — the fallback when no ontology.yaml is present (ADR-0024 §4).
# The ontology, when found, supplies these instead; these stay as the never-fail floor.
# Definitions here are the source of the prompt bullets — keep them byte-for-byte in
# sync with ontology.yaml's semantic-kind definitions (the tuned ADR-0013 text).
_DEFAULT_ENTITY_KINDS: tuple[tuple[str, str], ...] = (
    ("decision", "A resolved choice with rationale. Includes non-goals (decisions NOT to do something)."),
    ("constraint", "An externally imposed boundary (platform, resource, timeline). Not chosen — inherited."),
    ("invariant", "A property the system must always maintain. Internally chosen."),
    ("trade-off", "An explicit tension between competing qualities."),
    ("risk", "An identified threat to success, with potential impact."),
    ("workflow", "A sequenced process or pipeline."),
    ("interface", "A contract boundary — API surface, protocol, schema, integration point."),
    ("open-question", "An unresolved issue requiring future decision."),
)
# `stale-claim` is a valid kind but special-cased in the Rules section, not a bullet
# (ADR-0013 / ADR-0016: doc claim contradicting a known code entity, issue #4).
ENTITY_KINDS = frozenset({name for name, _ in _DEFAULT_ENTITY_KINDS} | {"stale-claim"})

# Relationship kinds for doc-to-doc and doc-to-code edges.
# These are the *semantic* (LLM-inferred) family per ADR-0021 — pure relationship verbs
# with zero overlap against code keywords. Structural `implements`/`inherits`/`imports`
# are emitted only by the parser handlers, never by the extractor.
_DEFAULT_RELATIONSHIP_KINDS: tuple[tuple[str, str], ...] = (
    ("realizes", "A code entity realizes a doc entity (e.g., a class realizes a decision or invariant)."),
    ("governed-by", "Code or design is constrained by a rule (invariant, constraint)."),
    ("motivates", "One entity is the reason another exists."),
    ("supersedes", "One decision replaces another."),
    ("addresses", "A decision resolves an open question."),
)
RELATIONSHIP_KINDS = frozenset({name for name, _ in _DEFAULT_RELATIONSHIP_KINDS})

# The prompt scaffolding (Rules + Output format) is fixed; only the kind bullets vary,
# so the same prompt can be rebuilt from any vocabulary (ADR-0024). `.format()` is avoided
# because the Output-format example contains literal `{` JSON braces.
_PROMPT_HEAD = """\
You are an entity extractor for a software documentation knowledge graph.
Given a chunk of technical documentation, extract entities and relationships.

## Entity kinds (use ONLY these)
"""
_PROMPT_MID = """

## Relationship kinds (use ONLY these)
"""
_PROMPT_TAIL = """

## Rules
- Extract 1-8 entities per chunk. Prefer fewer, higher-quality entities over many vague ones.
- Entity names should be specific and reusable (e.g., "pre-commit hook regeneration" not "the approach").
- If the text references code constructs (class names, function names, module names), emit \
relationships linking the doc entity to the code construct name.
- For relationships, source_name and target_name must be entity names from this chunk or \
well-known code identifiers referenced in the text.
- CRITICAL: when a concept in the chunk corresponds to an entity in "## Known code entities" \
below, use that entity's EXACT name as the relationship target_name (and reuse the name rather \
than inventing a synonym). This is how documentation gets linked to its implementation.
- Use canonical terms from "## Canonical vocabulary" when they match concepts in the chunk, \
instead of coining a new name for the same concept.
- If a claim in the chunk directly contradicts a known code entity (says something is missing/ \
unbuilt that the code shows exists), extract it with kind "stale-claim".

## Output format
Return ONLY valid JSON, no markdown fences, no commentary:
{"entities": [{"name": "...", "kind": "...", "description": "..."}], \
"relationships": [{"source_name": "...", "target_name": "...", "kind": "...", "description": "..."}]}

If the chunk contains no extractable entities, return: {"entities": [], "relationships": []}
"""


def build_system_prompt(entity_bullets: str, relationship_bullets: str) -> str:
    """Assemble the extraction prompt from kind bullets and the fixed scaffolding."""
    return _PROMPT_HEAD + entity_bullets + _PROMPT_MID + relationship_bullets + _PROMPT_TAIL


def _default_bullets(kinds: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"- {name}: {definition}" for name, definition in kinds)


_SYSTEM_PROMPT = build_system_prompt(
    _default_bullets(_DEFAULT_ENTITY_KINDS),
    _default_bullets(_DEFAULT_RELATIONSHIP_KINDS),
)


class Summarizer(Protocol):
    """Extract entities and relationships from a source-file chunk."""

    def summarize(self, text: str, *, context: str = "") -> tuple[list[RawEntity], list[RawRelationship]]:
        """Best-effort extraction. `context` is the ADR-0016 prefix (known code entities,
        canonical vocabulary, source metadata). Quality is not guaranteed (§2.2 Does not own)."""
        ...

    def summarize_scope(self, scope_name: str, entity_descriptions: list[str]) -> str | None:
        """Produce a ~500-token orientation summary for a scope. Returns None on failure."""
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


_SCOPE_SUMMARY_PROMPT = """\
You are writing an orientation summary for a scope (directory) in a software project.
Given the entity descriptions from this scope, produce a concise markdown summary
that helps an agent or engineer understand:

1. What this scope does — its purpose and responsibility
2. Key interfaces — the public API surface other code interacts with
3. Internal structure — major classes, protocols, and how they relate
4. Dependencies — what this scope imports from or connects to

## Rules
- Write 2-4 paragraphs of prose, ~300-500 tokens total.
- Lead with what the scope DOES, not what it contains.
- Name specific classes, functions, and protocols — be concrete.
- Mention design patterns (e.g., "hides the backend choice behind a Protocol").
- Do NOT list every entity. Summarize; highlight what matters for orientation.
- Do NOT use markdown headers — this will be embedded inside an AGENTS.md file.
- Write in present tense, third person ("The ingester reads...", "This scope handles...").
"""


def _cache_key(text: str, model: str, context: str = "", ontology: str = "") -> str:
    # context is part of the prompt (ADR-0016), so it must key the cache: changing the
    # known-code-entity prefix must invalidate doc extractions that depended on it.
    # The ontology hash is likewise part of the prompt now (ADR-0024) — a vocabulary edit
    # must re-extract — so it keys the cache too.
    return hashlib.sha256(f"{_CACHE_VERSION}:{model}:{ontology}:{context}:{text}".encode()).hexdigest()


class LLMSummarizer:
    """Concrete Summarizer that calls an OpenAI-compatible LLM endpoint.

    Caches entity extraction results per chunk (content-addressed, model-aware)
    to avoid redundant LLM calls on re-ingest of unchanged files.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        cache_dir: Path | None = None,
        *,
        api_key: str | None = None,
        metrics: "LLMMetrics | None" = None,
        ontology: "Ontology | None" = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._cache_dir = cache_dir
        self._api_key = api_key
        self._metrics = metrics
        self._client = build_client(timeout=120.0)
        self.set_ontology(ontology)
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_hits = 0
        self._cache_misses = 0

    def set_ontology(self, ontology: "Ontology | None") -> None:
        """Derive the prompt + validation kinds + cache hash from `ontology` (ADR-0024 §4).

        Re-callable so a portfolio ingest can swap in each project's COMPOSED ontology
        before that project's chunks (ADR-0025 §5): the per-project ontology hash keys the
        cache, so an overlay edit re-extracts only that project. `None` → hardcoded defaults.
        """
        if ontology is not None:
            self._system_prompt = build_system_prompt(
                ontology.entity_bullets(), ontology.relationship_bullets()
            )
            self._entity_kinds = ontology.entity_kinds()
            self._relationship_kinds = ontology.relationship_kinds()
            self._ontology_hash = ontology.content_hash
        else:
            self._system_prompt = _SYSTEM_PROMPT
            self._entity_kinds = ENTITY_KINDS
            self._relationship_kinds = RELATIONSHIP_KINDS
            self._ontology_hash = ""

    def _cache_path(self, key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{key}.json"

    def _read_cache(self, text: str, context: str = "") -> tuple[list[RawEntity], list[RawRelationship]] | None:
        path = self._cache_path(_cache_key(text, self._model, context, self._ontology_hash))
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entities = [RawEntity(name=e["name"], kind=e["kind"], description=e["description"]) for e in data.get("entities", [])]
            relationships = [RawRelationship(source_name=r["source_name"], target_name=r["target_name"], kind=r["kind"], description=r["description"]) for r in data.get("relationships", [])]
            return entities, relationships
        except Exception:
            return None

    def _write_cache(self, text: str, entities: list[RawEntity], relationships: list[RawRelationship], context: str = "") -> None:
        path = self._cache_path(_cache_key(text, self._model, context, self._ontology_hash))
        if path is None:
            return
        data = {
            "entities": [{"name": e.name, "kind": e.kind, "description": e.description} for e in entities],
            "relationships": [{"source_name": r.source_name, "target_name": r.target_name, "kind": r.kind, "description": r.description} for r in relationships],
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    def _chat(self, system: str, user: str, max_tokens: int = 2048) -> str | None:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }

        # OpenAI/Azure reasoning models (gpt-5.x, o-series) reject `max_tokens`
        # and require `max_completion_tokens`. Local llama.cpp / deepseek use `max_tokens`.
        if self._model.startswith(("gpt-5", "o1", "o3", "o4")):
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens

        if self._model.startswith("deepseek"):
            body["thinking"] = {"type": "disabled"}

        t0 = time.monotonic()
        try:
            resp = post_with_retry(
                self._client,
                f"{self._endpoint}/chat/completions",
                json=body,
                headers=headers or None,
            )
            data = resp.json()
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
            cache_miss_tokens = usage.get("prompt_cache_miss_tokens", 0)

            if self._metrics:
                self._metrics.record_chat(
                    input_tokens, output_tokens, elapsed_ms,
                    cache_hit_tokens=cache_hit_tokens,
                    cache_miss_tokens=cache_miss_tokens,
                )

            log.debug(
                "chat_completion",
                extra={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_hit_tokens": cache_hit_tokens,
                    "cache_miss_tokens": cache_miss_tokens,
                    "elapsed_ms": elapsed_ms,
                },
            )

            return data["choices"][0]["message"]["content"]
        except Exception:
            log.warning("LLM call failed (system prompt len=%d, user len=%d)", len(system), len(user), exc_info=True)
            return None

    def summarize(self, text: str, *, context: str = "") -> tuple[list[RawEntity], list[RawRelationship]]:
        cached = self._read_cache(text, context)
        if cached is not None:
            self._cache_hits += 1
            if self._metrics:
                self._metrics.record_cache_hit()
            return cached

        self._cache_misses += 1
        if self._metrics:
            self._metrics.record_cache_miss()

        # ADR-0016: prepend the run-constant context (known code entities, vocabulary,
        # source metadata) so the LLM references real identifiers and canonical terms.
        user = f"{context}\n\n## Chunk to extract from\n{text}" if context else text
        content = self._chat(self._system_prompt, user)
        if content is None:
            return [], []

        entities, relationships = _parse_llm_response(content)
        self._write_cache(text, entities, relationships, context)
        return entities, relationships

    def summarize_scope(self, scope_name: str, entity_descriptions: list[str]) -> str | None:
        combined = "\n\n---\n\n".join(entity_descriptions)
        if len(combined) > 12000:
            combined = combined[:12000] + "\n\n[... truncated]"

        user_msg = f"Scope: {scope_name}/\n\nEntities in this scope:\n\n{combined}"
        content = self._chat(_SCOPE_SUMMARY_PROMPT, user_msg, max_tokens=1024)
        if content is None:
            return None
        return content.strip()
