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
    graph_commit: str | None


_TABLE_HEADER = "| timestamp | invocation | command | args | duration_ms | exit | graph_commit |\n|---|---|---|---|---|---|---|\n"


def append(journal_path: Path, entry: JournalEntry) -> None:
    """Append one structured entry. Bounded volume per invariant 4."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    ts = entry.started_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    args_str = " ".join(entry.args) if entry.args else ""
    gc = entry.graph_commit[:8] if entry.graph_commit else "-"
    row = f"| {ts} | {entry.invocation_id} | {entry.command} | {args_str} | {entry.duration_ms} | {entry.exit_code} | {gc} |\n"

    if not journal_path.exists():
        journal_path.write_text(_TABLE_HEADER + row)
    else:
        with open(journal_path, "a") as f:
            f.write(row)
