"""Tests for the ConfigStore. See ARCHITECTURE.md §3.1."""

from pathlib import Path

from context_kernel.config_store import Config, IngesterConfig, load


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
