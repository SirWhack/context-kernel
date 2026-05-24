"""Cross-cutting view rendering: by-topic, recent-changes, index. See ARCHITECTURE.md §2.3."""

from context_kernel.graph.protocol import KnowledgeStore
from context_kernel.types import ViewSpec


def render_view(spec: ViewSpec, store: KnowledgeStore) -> str:
    """Render one configured [[view]] into markdown."""
    raise NotImplementedError("TODO(impl)")
