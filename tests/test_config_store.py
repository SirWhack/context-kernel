"""Tests for the ConfigStore. See ARCHITECTURE.md §3.1."""

from pathlib import Path

import pytest

from context_kernel.config_store import Config, IngesterConfig, ProjectSpec, load


class TestLoadDefaults:
    def test_defaults_when_no_file(self):
        config = load(Path("/nonexistent/config.toml"))
        assert isinstance(config, Config)
        assert config.ingester.summarizer_model == "qwen3-30b-a3b-instruct-2507"
        assert config.ingester.embedder_model == "qwen3-embedding-0.6b"
        assert config.ingester.embedder_dim == 1024
        assert config.ingester.storage_backend == "networkx"
        assert config.ingester.summary_target_tokens == 500

    def test_defaults_when_none(self):
        config = load(None)
        assert config.ingester.summarizer_endpoint == "http://127.0.0.1:8080/v1"
        assert config.ingester.embedder_endpoint == "http://127.0.0.1:8081/v1"
        assert config.materializer.views == []
        assert config.orientation.default_max_tokens == 4096

    def test_loads_from_toml(self, tmp_path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            '[ingester]\nsummarizer_model = "custom-model"\nsummary_target_tokens = 300\n'
        )
        config = load(toml)
        assert config.ingester.summarizer_model == "custom-model"
        assert config.ingester.summary_target_tokens == 300
        assert config.ingester.embedder_model == "qwen3-embedding-0.6b"

    def test_exclude_dirs_parsed_as_tuple(self, tmp_path):
        # TOML arrays parse to lists; the frozen dataclass needs a hashable tuple.
        toml = tmp_path / "config.toml"
        toml.write_text('[ingester]\nexclude_dirs = ["test-repos", "vendor"]\n')
        config = load(toml)
        assert config.ingester.exclude_dirs == ("test-repos", "vendor")

    def test_exclude_dirs_default_empty(self):
        assert load(None).ingester.exclude_dirs == ()

    def test_portfolio_root_defaults_to_cwd(self):
        config = load(None)
        assert config.portfolio_root == Path(".").resolve()

    def test_views_parsed(self, tmp_path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            '[[materializer.views]]\nname = "by-topic"\nkind = "tag"\n\n'
            '[materializer.views.params]\ntag = "auth"\n'
        )
        config = load(toml)
        assert len(config.materializer.views) == 1
        assert config.materializer.views[0].name == "by-topic"


class TestProjectSpec:
    def test_name_derived_from_path(self):
        spec = ProjectSpec(path=Path("model-time"))
        assert spec.name == "model-time"

    def test_name_from_nested_path(self):
        spec = ProjectSpec(path=Path("sub/deep-project"))
        assert spec.name == "deep-project"


class TestProjectsLoading:
    def test_default_single_project_when_absent(self):
        config = load(None)
        assert len(config.projects) == 1
        assert config.projects[0].path == Path(".")

    def test_parses_projects_table(self, tmp_path):
        proj_a = tmp_path / "proj-a"
        proj_b = tmp_path / "proj-b"
        proj_a.mkdir()
        proj_b.mkdir()
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "proj-a"\n\n'
            '[[projects]]\npath = "proj-b"\n'
        )
        config = load(toml)
        assert len(config.projects) == 2
        assert config.projects[0].name == "proj-a"
        assert config.projects[1].name == "proj-b"

    def test_rejects_absolute_path(self, tmp_path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "/absolute/path"\n'
        )
        with pytest.raises(ValueError, match="must be relative"):
            load(toml)

    def test_rejects_empty_name(self, tmp_path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "."\n'
        )
        with pytest.raises(ValueError, match="empty name"):
            load(toml)

    def test_rejects_invalid_name(self, tmp_path):
        proj = tmp_path / "has spaces"
        proj.mkdir()
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "has spaces"\n'
        )
        with pytest.raises(ValueError, match="must match"):
            load(toml)

    def test_rejects_duplicate_names(self, tmp_path):
        (tmp_path / "foo").mkdir()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "foo").mkdir()
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "foo"\n\n'
            '[[projects]]\npath = "sub/foo"\n'
        )
        with pytest.raises(ValueError, match="Duplicate project name"):
            load(toml)

    def test_rejects_nonexistent_path(self, tmp_path):
        toml = tmp_path / "config.toml"
        toml.write_text(
            f'portfolio_root = "{tmp_path}"\n\n'
            '[[projects]]\npath = "ghost"\n'
        )
        with pytest.raises(ValueError, match="does not exist"):
            load(toml)
