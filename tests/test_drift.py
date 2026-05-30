"""Drift via git churn (Slice 3, ADR-0020).

Unit tests for the change_detection git layer (commit_of / churn / size) and the
edge_drift composition, exercised against a real temporary git repository.
"""

import subprocess

import pytest

from context_kernel import change_detection as cd
from context_kernel import scoring
from context_kernel.config_store import IngesterConfig
from context_kernel.ingester import ingest
from context_kernel.ingester.handlers import RawEntity, RawRelationship


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


# ── Ingest integration (Slice 4) ────────────────────────────────────────────


class _CapturingStore:
    """Minimal KnowledgeStore capturing the upsert for assertions."""

    def __init__(self):
        self.entities = []
        self.relationships = []

    def graph_commit(self):
        from context_kernel.types import GraphCommit
        return GraphCommit("initial")

    def get_entity(self, entity_id):
        return None

    def get_neighbors(self, entity_id):
        return []

    def get_summary(self, scope):
        return None

    def get_embedding(self, digest):
        return None

    def search_similar(self, query_embedding, k, scope=None):
        return []

    def list_summaries(self):
        return []

    def list_entities_by_scope(self):
        return {}

    def upsert(self, graph_commit, entities, relationships, summaries, chunks=None, scope_entities=None):
        self.entities = list(entities)
        self.relationships = list(relationships)


class _RealizesSummarizer:
    """Emits one decision entity per chunk plus a `realizes` edge to a fixed code symbol."""

    def __init__(self, target, name="doc claim"):
        self.target = target
        self.name = name
        self.calls = []

    def summarize(self, text, *, context=""):
        self.calls.append(text)
        self.last_context = context
        ents = [RawEntity(name=self.name, kind="decision", description=f"claim about {self.target}")]
        rels = [RawRelationship(source_name=self.name, target_name=self.target, kind="realizes", description="")]
        return ents, rels

    def summarize_scope(self, scope_name, entity_descriptions):
        return f"summary: {len(entity_descriptions)} entities"


def _ent(store, name):
    return next((e for e in store.entities if e.name == name), None)


class TestIngestScoringPass:
    def test_stale_referent_doc_gets_low_confidence(self, repo):
        code = repo / "summarizer.py"
        doc = repo / "design.md"
        code.write_text("class LLMSummarizer:\n" + "".join(f"    x{i} = {i}\n" for i in range(12)))
        doc.write_text("# Design\n\nThe LLMSummarizer realizes the extraction decision.\n")
        _commit(repo, "c1: doc + code")

        # code is rewritten after the doc's commit → the doc's claim drifts
        code.write_text("class LLMSummarizer:\n" + "".join(f"    y{i} = {i*2}\n" for i in range(12)))
        _commit(repo, "c2: rewrite code")

        store = _CapturingStore()
        ingest(store, repo, repo, IngesterConfig(), summarizer=_RealizesSummarizer("LLMSummarizer"))

        doc_ent = _ent(store, "doc claim")
        assert doc_ent is not None
        # drift loaded on the doc side → confidence is strictly below raw authority
        assert doc_ent.confidence < doc_ent.source_tier
        # and the realizes edge carries the drift
        realizes = [r for r in store.relationships if r.kind == "realizes"]
        assert realizes and realizes[0].drift > 0.0

    def test_stable_doc_keeps_full_confidence(self, repo):
        code = repo / "summarizer.py"
        doc = repo / "design.md"
        code.write_text("class LLMSummarizer:\n    pass\n")
        doc.write_text("# Design\n\nThe LLMSummarizer realizes the extraction decision.\n")
        _commit(repo, "c1: doc + code, both current")

        store = _CapturingStore()
        ingest(store, repo, repo, IngesterConfig(), summarizer=_RealizesSummarizer("LLMSummarizer"))

        doc_ent = _ent(store, "doc claim")
        assert doc_ent is not None
        # nothing churned after the doc's commit → no drift → confidence == authority
        assert doc_ent.confidence == pytest.approx(doc_ent.source_tier)
        realizes = [r for r in store.relationships if r.kind == "realizes"]
        assert realizes and realizes[0].drift == 0.0

    def test_code_referenced_by_many_docs_is_central(self, repo):
        code = repo / "store.py"
        code.write_text("class KnowledgeStore:\n    pass\n")
        (repo / "a.md").write_text("# A\n\nKnowledgeStore is the backbone.\n")
        (repo / "b.md").write_text("# B\n\nKnowledgeStore holds the graph.\n")
        _commit(repo, "c1")

        store = _CapturingStore()
        ingest(store, repo, repo, IngesterConfig(), summarizer=_RealizesSummarizer("KnowledgeStore"))

        code_ent = _ent(store, "KnowledgeStore")
        assert code_ent is not None
        # two distinct documents realize it → top of the normalized centrality range
        assert code_ent.centrality == 1.0
