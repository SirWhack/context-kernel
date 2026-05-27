"""Tests for the reference doc pointer and gap detection system. See ADR-0014."""

from pathlib import Path

from context_kernel.graph.protocol import Entity
from context_kernel.materializer.reference_docs import (
    detect_documentation_gap,
    find_reference_doc,
    render_gap_recommendation,
    render_reference_pointer,
)
from context_kernel.types import ScopePath


def _make_code_entities(n: int, *, with_files: bool = False) -> list[Entity]:
    """Generate *n* code entities (kind=function). Optionally include File: lines in descriptions."""
    entities: list[Entity] = []
    for i in range(n):
        file_line = f"\nFile: src/mod_{i % 3}.py" if with_files else ""
        entities.append(
            Entity(
                id=f"e{i}",
                name=f"func_{i}",
                kind="function",
                description=f"Does thing {i}.{file_line}",
            )
        )
    return entities


class TestFindReferenceDoc:
    def test_finds_by_leaf_name(self, tmp_path):
        ref_dir = tmp_path / "docs" / "reference"
        ref_dir.mkdir(parents=True)
        (ref_dir / "ingester.md").write_text("# Ingester reference\n")
        scope = ScopePath(Path("context_kernel/ingester"))
        result = find_reference_doc(scope, tmp_path)
        assert result is not None
        assert result == ref_dir / "ingester.md"

    def test_returns_none_when_missing(self, tmp_path):
        scope = ScopePath(Path("context_kernel/ingester"))
        result = find_reference_doc(scope, tmp_path)
        assert result is None

    def test_nested_scope_uses_leaf(self, tmp_path):
        ref_dir = tmp_path / "docs" / "reference"
        ref_dir.mkdir(parents=True)
        (ref_dir / "handlers.md").write_text("# Handlers\n")
        scope = ScopePath(Path("context_kernel/ingester/handlers"))
        result = find_reference_doc(scope, tmp_path)
        assert result is not None
        assert result.name == "handlers.md"

    def test_root_scope(self, tmp_path):
        ref_dir = tmp_path / "docs" / "reference"
        ref_dir.mkdir(parents=True)
        (ref_dir / "myproject.md").write_text("# Root ref\n")
        scope = ScopePath(Path("myproject"))
        result = find_reference_doc(scope, tmp_path)
        assert result is not None
        assert result.name == "myproject.md"


class TestDetectDocumentationGap:
    def test_above_threshold_no_doc(self, tmp_path):
        scope = ScopePath(Path("src"))
        entities = _make_code_entities(12, with_files=True)
        result = detect_documentation_gap(scope, entities, tmp_path)
        assert result is not None
        assert "Recommended documentation" in result
        assert "12 code entities" in result

    def test_below_threshold(self, tmp_path):
        scope = ScopePath(Path("src"))
        entities = _make_code_entities(5)
        result = detect_documentation_gap(scope, entities, tmp_path)
        assert result is None

    def test_above_threshold_with_doc(self, tmp_path):
        ref_dir = tmp_path / "docs" / "reference"
        ref_dir.mkdir(parents=True)
        (ref_dir / "src.md").write_text("# Src reference\n")
        scope = ScopePath(Path("src"))
        entities = _make_code_entities(15)
        result = detect_documentation_gap(scope, entities, tmp_path)
        assert result is None

    def test_custom_threshold(self, tmp_path):
        scope = ScopePath(Path("src"))
        entities = _make_code_entities(3)
        result = detect_documentation_gap(scope, entities, tmp_path, threshold=3)
        assert result is not None
        assert "3 code entities" in result

    def test_only_counts_code_entities(self, tmp_path):
        scope = ScopePath(Path("src"))
        # 8 code entities + 5 non-code entities = 13 total, but only 8 code
        code = _make_code_entities(8)
        non_code = [
            Entity(id=f"nc{i}", name=f"concept_{i}", kind="concept", description=f"Concept {i}.")
            for i in range(5)
        ]
        result = detect_documentation_gap(scope, code + non_code, tmp_path, threshold=10)
        assert result is None  # 8 < 10


class TestRenderSections:
    def test_pointer_includes_relative_path(self):
        tree_root = Path("/project")
        scope = ScopePath(Path("context_kernel/ingester"))
        ref_path = tree_root / "docs" / "reference" / "ingester.md"
        result = render_reference_pointer(ref_path, scope, tree_root)
        assert "## Reference documentation" in result
        assert "ingester.md" in result
        # The relative path from /project/context_kernel/ingester to /project/docs/reference/ingester.md
        assert "../../docs/reference/ingester.md" in result

    def test_gap_includes_entity_and_file_counts(self):
        scope = ScopePath(Path("src/auth"))
        result = render_gap_recommendation(scope, 15, 4)
        assert "15 code entities" in result
        assert "4 files" in result

    def test_gap_includes_init_reference_command(self):
        scope = ScopePath(Path("context_kernel/ingester"))
        result = render_gap_recommendation(scope, 20, 6)
        assert "/init-reference ingester" in result
