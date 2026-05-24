"""OperationalJournal — append-only .context-kernel/log.md. See ARCHITECTURE.md §3.2, invariant 4."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

# Does not own:
#   - module-layer consumption (operator-only; never read on the request path)
#   - automatic rotation (operator-triggered archival in v1)
#   - content logging (hashes only, never file contents — invariant 4)


@dataclass(frozen=True)
class JournalEntry:
    invocation_id: UUID
    started_at: datetime
    command: str
    args: list[str]
    duration_ms: int
    exit_code: int
    regen_chain: list[str]


def append(journal_path: Path, entry: JournalEntry) -> None:
    """Append one structured entry. Bounded volume per invariant 4."""
    raise NotImplementedError("TODO(impl)")
