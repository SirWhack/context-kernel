"""Summarizer Parnas-secret — hides which LLM produces entity-extraction summaries. See ARCHITECTURE.md §2.2."""

from typing import Protocol

from context_kernel.graph.protocol import Entity, Relationship


class Summarizer(Protocol):
    """Extract entities and relationships from a source-file chunk."""

    def summarize(self, text: str) -> tuple[list[Entity], list[Relationship]]:
        """Best-effort extraction. Quality is not guaranteed (§2.2 Does not own)."""
        ...
