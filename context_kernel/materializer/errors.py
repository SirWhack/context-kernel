"""MaterializationError. See ARCHITECTURE.md §5."""

from context_kernel.types import GraphCommit, ScopePath


class MaterializationError(Exception):
    """Raised by Materializer with scope + graph_commit context."""

    def __init__(
        self,
        message: str,
        scope: ScopePath,
        graph_commit: GraphCommit,
    ) -> None:
        super().__init__(message)
        self.scope = scope
        self.graph_commit = graph_commit
