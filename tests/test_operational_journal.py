"""Tests for the OperationalJournal. See ARCHITECTURE.md §3.2."""

from datetime import datetime, timezone
from uuid import uuid4

from context_kernel.operational_journal import JournalEntry, append


class TestAppend:
    def test_creates_file_with_header(self, tmp_path):
        path = tmp_path / ".context-kernel" / "log.md"
        entry = JournalEntry(
            invocation_id=uuid4(),
            started_at=datetime(2026, 5, 24, 15, 30, 0, tzinfo=timezone.utc),
            command="ingest",
            args=["--portfolio", "."],
            duration_ms=12345,
            exit_code=0,
            regen_chain=[],
        )
        append(path, entry)
        text = path.read_text()
        assert "timestamp" in text
        assert "ingest" in text
        assert "12345" in text

    def test_appends_to_existing(self, tmp_path):
        path = tmp_path / "log.md"
        e1 = JournalEntry(
            invocation_id=uuid4(),
            started_at=datetime(2026, 5, 24, 15, 0, 0, tzinfo=timezone.utc),
            command="ingest",
            args=[],
            duration_ms=100,
            exit_code=0,
            regen_chain=[],
        )
        e2 = JournalEntry(
            invocation_id=uuid4(),
            started_at=datetime(2026, 5, 24, 15, 1, 0, tzinfo=timezone.utc),
            command="materialize",
            args=["--all"],
            duration_ms=50,
            exit_code=0,
            regen_chain=[],
        )
        append(path, e1)
        append(path, e2)
        text = path.read_text()
        assert text.count("ingest") == 1
        assert text.count("materialize") == 1

    def test_invocation_id_in_output(self, tmp_path):
        path = tmp_path / "log.md"
        uid = uuid4()
        entry = JournalEntry(
            invocation_id=uid,
            started_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
            command="check",
            args=["AGENTS.md"],
            duration_ms=23,
            exit_code=1,
            regen_chain=[],
        )
        append(path, entry)
        assert str(uid) in path.read_text()
