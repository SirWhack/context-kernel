"""Tests for the AgentCLI. See ARCHITECTURE.md §2.6."""

import subprocess

from context_kernel.agent_cli import _build_parser, _cmd_init


class TestArgParsing:
    def test_init(self):
        parser = _build_parser()
        args = parser.parse_args(["init"])
        assert args.command == "init"

    def test_init_with_portfolio(self, tmp_path):
        parser = _build_parser()
        args = parser.parse_args(["init", "--portfolio", str(tmp_path)])
        assert args.command == "init"
        assert args.portfolio == tmp_path

    def test_ingest_default(self):
        parser = _build_parser()
        args = parser.parse_args(["ingest"])
        assert args.command == "ingest"

    def test_ingest_with_portfolio(self, tmp_path):
        parser = _build_parser()
        args = parser.parse_args(["ingest", "--portfolio", str(tmp_path)])
        assert args.command == "ingest"
        assert args.portfolio == tmp_path

    def test_materialize_all(self):
        parser = _build_parser()
        args = parser.parse_args(["materialize", "--all"])
        assert args.command == "materialize"
        assert args.all_scopes is True

    def test_materialize_scope(self, tmp_path):
        parser = _build_parser()
        args = parser.parse_args(["materialize", "--scope", "src/auth"])
        assert args.command == "materialize"

    def test_check_path(self, tmp_path):
        parser = _build_parser()
        args = parser.parse_args(["check", str(tmp_path / "AGENTS.md")])
        assert args.command == "check"

    def test_mcp(self):
        parser = _build_parser()
        args = parser.parse_args(["mcp"])
        assert args.command == "mcp"


class TestCkInit:
    def test_init_in_git_repo(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        hooks_dir = tmp_path / ".githooks"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/bash\n")

        parser = _build_parser()
        args = parser.parse_args(["init", "--portfolio", str(tmp_path)])
        result = _cmd_init(args)
        assert result == 0

        config_out = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert config_out.stdout.strip() == ".githooks"

    def test_init_not_git_repo(self, tmp_path):
        parser = _build_parser()
        args = parser.parse_args(["init", "--portfolio", str(tmp_path)])
        result = _cmd_init(args)
        assert result == 1

    def test_init_no_hooks_dir(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        parser = _build_parser()
        args = parser.parse_args(["init", "--portfolio", str(tmp_path)])
        result = _cmd_init(args)
        assert result == 1
