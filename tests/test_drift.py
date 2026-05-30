"""Drift via git churn (Slice 3, ADR-0020).

Unit tests for the change_detection git layer (commit_of / churn / size) and the
edge_drift composition, exercised against a real temporary git repository.
"""

import subprocess

import pytest

from context_kernel import change_detection as cd
from context_kernel import scoring


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    cd._clear_git_caches()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    cd._clear_git_caches()
    yield tmp_path
    cd._clear_git_caches()


class TestCommitOf:
    def test_tracked_file_has_commit(self, repo):
        (repo / "code.py").write_text("x = 1\n")
        _commit(repo, "add code")
        assert cd.commit_of(str(repo / "code.py")) is not None

    def test_untracked_file_is_none(self, repo):
        (repo / "loose.py").write_text("y = 2\n")  # never committed
        assert cd.commit_of(str(repo / "loose.py")) is None

    def test_not_a_repo_is_none(self, tmp_path):
        (tmp_path / "x.py").write_text("z = 3\n")
        assert cd.commit_of(str(tmp_path / "x.py")) is None


class TestSize:
    def test_line_count(self, repo):
        (repo / "code.py").write_text("a\nb\nc\n")
        assert cd.size(str(repo / "code.py")) == 3

    def test_no_trailing_newline_counted(self, repo):
        (repo / "code.py").write_text("a\nb")
        assert cd.size(str(repo / "code.py")) == 2

    def test_missing_file_is_zero(self, repo):
        assert cd.size(str(repo / "nope.py")) == 0


class TestChurn:
    def test_since_none_is_zero(self, repo):
        (repo / "code.py").write_text("a\n")
        _commit(repo, "c1")
        assert cd.churn(str(repo / "code.py"), None) == 0

    def test_counts_lines_changed_after_since(self, repo):
        code = repo / "code.py"
        code.write_text("a\nb\nc\n")
        _commit(repo, "c1")
        since = cd.commit_of(str(code))
        code.write_text("a\nB\nc\nd\ne\n")  # 1 changed + 2 added → numstat 3 added, 1 removed
        _commit(repo, "c2")
        assert cd.churn(str(code), since) > 0

    def test_no_change_after_since_is_zero(self, repo):
        code = repo / "code.py"
        code.write_text("a\nb\n")
        _commit(repo, "c1")
        since = cd.commit_of(str(code))  # HEAD == since → empty interval
        assert cd.churn(str(code), since) == 0


class TestDriftScenario:
    """The ADR-0020 worked example: code churns under a doc's stale claim."""

    def test_code_churn_drives_doc_side_drift(self, repo):
        code = repo / "summarizer.py"
        doc = repo / "HANDOFF.md"
        code.write_text("".join(f"line{i}\n" for i in range(10)))
        doc.write_text("LLMSummarizer is not yet wired.\n")
        _commit(repo, "c1: doc + code together")

        # doc's last commit is the drift reference point
        since = cd.commit_of(str(doc))

        # code is then implemented — a near-rewrite
        code.write_text("".join(f"impl{i}\n" for i in range(10)))
        _commit(repo, "c2: implement summarizer")

        lines = cd.churn(str(code), since)
        drift = scoring.edge_drift(lines, cd.size(str(code)))
        assert drift > 0.5  # large change relative to a 10-line referent → high drift

    def test_touching_doc_resets_drift(self, repo):
        code = repo / "summarizer.py"
        doc = repo / "HANDOFF.md"
        code.write_text("".join(f"line{i}\n" for i in range(10)))
        doc.write_text("stale claim\n")
        _commit(repo, "c1")

        code.write_text("".join(f"impl{i}\n" for i in range(10)))
        _commit(repo, "c2: code moves")

        doc.write_text("reviewed: summarizer is implemented\n")
        _commit(repo, "c3: update the doc")

        # claimant's last commit is now c3; nothing churned the referent after it
        since = cd.commit_of(str(doc))
        drift = scoring.edge_drift(cd.churn(str(code), since), cd.size(str(code)))
        assert drift == 0.0

    def test_doc_edit_does_not_drift_stable_code(self, repo):
        # editing a doc must never make stable code look stale: code is the referent,
        # and its churn (not the doc's) drives drift.
        code = repo / "stable.py"
        doc = repo / "notes.md"
        code.write_text("".join(f"line{i}\n" for i in range(20)))
        doc.write_text("v1\n")
        _commit(repo, "c1")

        # code is the referent; its claimant-edge reference point is the code's own
        # last commit. Edit only the doc.
        since = cd.commit_of(str(code))
        doc.write_text("v2 — lots of new prose\nmore\nlines\n")
        _commit(repo, "c2: doc only")

        # churn to the *code* since the code last changed is 0 → no drift on edges
        # where code is the claimant.
        assert cd.churn(str(code), since) == 0
