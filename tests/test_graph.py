"""Tests for the Graph module. See ARCHITECTURE.md §2.1."""

# TODO(test): KnowledgeStore protocol conformance; LightRAGStore round-trip; addressing.hash_bytes / blob_path.
from context_kernel.graph import (  # noqa: F401
    Entity,
    KnowledgeStore,
    Neighbor,
    Relationship,
    Summary,
)
