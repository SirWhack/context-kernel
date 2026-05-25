"""Cross-cutting view rendering: index, by-topic. See ARCHITECTURE.md §2.3, S6 spec."""

from __future__ import annotations

from context_kernel.graph.protocol import Entity, KnowledgeStore, Summary
from context_kernel.types import ScopePath, ViewSpec


def _render_index(store: KnowledgeStore) -> str:
    summaries = store.list_summaries()
    if not summaries:
        return "# Index\n\nNo scopes materialized yet.\n"

    summaries.sort(key=lambda s: str(s.scope))
    lines = ["# Index\n"]
    for s in summaries:
        lines.append(f"## {s.scope}")
        lines.append(s.markdown)
        lines.append(f"→ {s.scope}/AGENTS.md\n")
    return "\n".join(lines) + "\n"


def _match(text: str, tag: str) -> bool:
    return tag in text.lower()


def _render_by_topic(store: KnowledgeStore, tag: str) -> str:
    tag_lower = tag.lower()
    entities_by_scope = store.list_entities_by_scope()
    summaries = {s.scope: s for s in store.list_summaries()}

    scope_results: dict[ScopePath, tuple[list[Entity], str | None]] = {}

    for scope, entities in sorted(entities_by_scope.items(), key=lambda kv: str(kv[0])):
        matched = [e for e in entities if _match(e.name, tag_lower) or _match(e.description, tag_lower)]
        summary = summaries.get(scope)
        summary_matches = summary is not None and _match(summary.markdown, tag_lower)

        if matched:
            scope_results[scope] = (matched, None)
        elif summary_matches:
            scope_results[scope] = ([], summary.markdown if summary else None)

    for scope, summary in sorted(summaries.items(), key=lambda kv: str(kv[0])):
        if scope not in scope_results and scope not in entities_by_scope and _match(summary.markdown, tag_lower):
            scope_results[scope] = ([], summary.markdown)

    if not scope_results:
        return f"# by-topic: {tag}\n\nNo matches found.\n"

    lines = [f"# by-topic: {tag}\n"]
    for scope in sorted(scope_results, key=lambda s: str(s)):
        matched_entities, fallback_summary = scope_results[scope]
        lines.append(f"## {scope}")
        lines.append(f"→ {scope}/AGENTS.md\n")
        if matched_entities:
            for e in matched_entities:
                lines.append(f"- **{e.name}** ({e.kind}): {e.description}")
            lines.append("")
        elif fallback_summary:
            lines.append(fallback_summary)
            lines.append("")
    return "\n".join(lines) + "\n"


def render_view(spec: ViewSpec, store: KnowledgeStore) -> str:
    if spec.kind == "index":
        return _render_index(store)
    elif spec.kind == "by-topic":
        tag = spec.params.get("tag", "")
        if not tag:
            return f"# by-topic\n\nNo tag configured in view spec '{spec.name}'.\n"
        return _render_by_topic(store, tag)
    else:
        return f"# {spec.name}\n\nUnknown view kind: {spec.kind}\n"
