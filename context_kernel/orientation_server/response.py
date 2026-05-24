"""Markdown response format + token-budget enforcement. See ARCHITECTURE.md §2.5."""

_CHARS_PER_TOKEN = 4


def assemble(chunks: list[str], source_paths: list[str], max_tokens: int) -> str:
    """Concatenate chunks with file-path citations, enforcing the token budget."""
    budget = max_tokens * _CHARS_PER_TOKEN
    parts: list[str] = []
    used = 0
    for chunk, path in zip(chunks, source_paths):
        citation = f"\n\n> Source: `{path}`\n"
        entry = chunk + citation
        if used + len(entry) > budget and parts:
            break
        parts.append(entry)
        used += len(entry)
    result = "\n".join(parts)
    if used > budget:
        cut = result[:budget]
        para = cut.rfind("\n\n")
        if para > budget // 2:
            result = cut[:para]
    return result
