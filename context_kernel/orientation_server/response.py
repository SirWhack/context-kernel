"""Markdown response format + token-budget enforcement. See ARCHITECTURE.md §2.5."""


def assemble(chunks: list[str], source_paths: list[str], max_tokens: int) -> str:
    """Concatenate chunks with file-path citations, enforcing the token budget."""
    raise NotImplementedError("TODO(impl)")
