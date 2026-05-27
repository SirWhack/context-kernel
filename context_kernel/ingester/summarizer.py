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

from context_kernel.ingester.handlers import RawEntity, RawRelationship

if TYPE_CHECKING:
    from context_kernel.types import LLMMetrics

log = logging.getLogger(__name__)

_CACHE_VERSION = "v2"

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


def _cache_key(text: str, model: str) -> str:
    return hashlib.sha256(f"{_CACHE_VERSION}:{model}:{text}".encode()).hexdigest()


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
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._cache_dir = cache_dir
        self._api_key = api_key
        self._metrics = metrics
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_path(self, key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{key}.json"

    def _read_cache(self, text: str) -> tuple[list[RawEntity], list[RawRelationship]] | None:
        path = self._cache_path(_cache_key(text, self._model))
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entities = [RawEntity(name=e["name"], kind=e["kind"], description=e["description"]) for e in data.get("entities", [])]
            relationships = [RawRelationship(source_name=r["source_name"], target_name=r["target_name"], kind=r["kind"], description=r["description"]) for r in data.get("relationships", [])]
            return entities, relationships
        except Exception:
            return None

    def _write_cache(self, text: str, entities: list[RawEntity], relationships: list[RawRelationship]) -> None:
        path = self._cache_path(_cache_key(text, self._model))
        if path is None:
            return
        data = {
            "entities": [{"name": e.name, "kind": e.kind, "description": e.description} for e in entities],
            "relationships": [{"source_name": r.source_name, "target_name": r.target_name, "kind": r.kind, "description": r.description} for r in relationships],
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    def _chat(self, system: str, user: str, max_tokens: int = 2048) -> str | None:
        import httpx

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
            "max_tokens": max_tokens,
        }

        if self._model.startswith("deepseek"):
            body["thinking"] = {"type": "disabled"}

        t0 = time.monotonic()
        try:
            resp = httpx.post(
                f"{self._endpoint}/chat/completions",
                json=body,
                headers=headers or None,
                timeout=120.0,
            )
            resp.raise_for_status()
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

    def summarize(self, text: str) -> tuple[list[RawEntity], list[RawRelationship]]:
        cached = self._read_cache(text)
        if cached is not None:
            self._cache_hits += 1
            if self._metrics:
                self._metrics.record_cache_hit()
            return cached

        self._cache_misses += 1
        if self._metrics:
            self._metrics.record_cache_miss()

        content = self._chat(_SYSTEM_PROMPT, text)
        if content is None:
            return [], []

        entities, relationships = _parse_llm_response(content)
        self._write_cache(text, entities, relationships)
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
