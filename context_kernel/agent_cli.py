"""AgentCLI — `ck` entrypoint. Dispatches to other modules. See ARCHITECTURE.md §2.6."""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from context_kernel.change_detection import register_excluded_dirs
from context_kernel.config_store import load as load_config
from context_kernel.logging import configure as configure_logging, invocation_id as _invocation_var
from context_kernel.operational_journal import JournalEntry, append

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ck", description="Context Kernel CLI")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Set up git hooks for documentation regeneration")
    init_p.add_argument("--portfolio", type=Path, default=Path("."))

    ingest_p = sub.add_parser("ingest")
    ingest_p.add_argument("--portfolio", type=Path, default=Path("."))
    ingest_p.add_argument("--config", type=Path, default=None)

    mat_p = sub.add_parser("materialize")
    mat_group = mat_p.add_mutually_exclusive_group()
    mat_group.add_argument("--scope", type=Path, default=None)
    mat_group.add_argument("--all", dest="all_scopes", action="store_true")
    mat_p.add_argument("--config", type=Path, default=None)

    check_p = sub.add_parser("check")
    check_p.add_argument("path", type=Path)
    check_p.add_argument("--config", type=Path, default=None)

    mcp_p = sub.add_parser("mcp")
    mcp_p.add_argument("--config", type=Path, default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    """Parse args; dispatch to `ingest` / `materialize` / `check` / `mcp`. Return a structured exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    config_path = getattr(args, "config", None)
    if config_path is None:
        portfolio = getattr(args, "portfolio", Path(".")).resolve()
        auto = portfolio / ".context-kernel" / "config.toml"
        if auto.exists():
            config_path = auto
    config = load_config(config_path)
    register_excluded_dirs(config.ingester.exclude_dirs)

    configure_logging()
    inv_id = uuid4()
    _invocation_var.set(str(inv_id))

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    exit_code = 0
    graph_commit: str | None = None

    try:
        if args.command == "init":
            return _cmd_init(args)
        elif args.command == "ingest":
            graph_commit = _cmd_ingest(args, config)
        elif args.command == "materialize":
            _cmd_materialize(args, config)
        elif args.command == "check":
            _cmd_check(args, config)
        elif args.command == "mcp":
            _cmd_mcp(args, config)
    except Exception as exc:
        log.error("ck %s: %s", args.command, exc)
        exit_code = 1

    duration_ms = int((time.monotonic() - t0) * 1000)
    journal_path = config.portfolio_root / ".context-kernel" / "log.md"
    raw_args = [str(v) for k, v in vars(args).items() if k not in {"command", "config"} and v is not None]
    entry = JournalEntry(
        invocation_id=inv_id,
        started_at=started,
        command=args.command,
        args=raw_args,
        duration_ms=duration_ms,
        exit_code=exit_code,
        graph_commit=graph_commit,
    )
    append(journal_path, entry)
    return exit_code


def _cmd_init(args: argparse.Namespace) -> int:
    portfolio = args.portfolio.resolve()
    git_dir = portfolio / ".git"
    hooks_dir = portfolio / ".githooks" / "pre-commit"
    if not git_dir.exists():
        log.error("ck init: not a git repository")
        return 1
    if not hooks_dir.exists():
        log.error("ck init: %s not found", hooks_dir)
        return 1
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=portfolio,
        check=True,
    )
    log.info("ck init: core.hooksPath set to .githooks in %s", portfolio)
    return 0


def _resolve_api_key(env_var: str) -> str | None:
    """Read API key from the named env var, falling back to CK_API_KEY."""
    return os.environ.get(env_var) or os.environ.get("CK_API_KEY")


def _build_store(portfolio: Path):
    from context_kernel.graph.lightrag_adapter import LightRAGStore
    return LightRAGStore(portfolio / ".context-kernel" / "graph")


def _build_embedder(config, api_key: str | None, metrics=None):
    from context_kernel.ingester.embedder import HttpEmbedder
    return HttpEmbedder(
        endpoint=config.ingester.embedder_endpoint,
        model=config.ingester.embedder_model,
        dim=config.ingester.embedder_dim,
        api_key=api_key,
        metrics=metrics,
    )


def _cmd_ingest(args: argparse.Namespace, config) -> str:
    from context_kernel.ingester import ingest_portfolio
    from context_kernel.ingester.summarizer import LLMSummarizer
    from context_kernel.types import LLMMetrics

    portfolio = args.portfolio.resolve()
    store = _build_store(portfolio)
    metrics = LLMMetrics()

    summarizer_key = _resolve_api_key(config.ingester.summarizer_api_key_env)
    embedder_key = _resolve_api_key(config.ingester.embedder_api_key_env)

    from context_kernel.ontology import load_ontology as load_ontology_yaml

    embedder = _build_embedder(config, embedder_key, metrics)
    ontology = load_ontology_yaml(portfolio)
    summarizer = LLMSummarizer(
        endpoint=config.ingester.summarizer_endpoint,
        model=config.ingester.summarizer_model,
        cache_dir=portfolio / ".context-kernel" / "cache",
        api_key=summarizer_key,
        metrics=metrics,
        ontology=ontology,
    )
    projects = [
        (project.path, None if project.path == Path(".") else project.name)
        for project in config.projects
    ]
    commit = ingest_portfolio(
        store,
        portfolio,
        portfolio,
        config.ingester,
        projects,
        summarizer=summarizer,
        embedder=embedder,
        metrics=metrics,
    )
    return str(commit)


def _cmd_materialize(args: argparse.Namespace, config) -> None:
    from context_kernel.change_detection import discover_scopes
    from context_kernel.materializer import materialize, materialize_view
    from context_kernel.types import ScopePath

    portfolio = config.portfolio_root
    store = _build_store(portfolio)
    all_written: list[Path] = []

    if args.all_scopes:
        for project in config.projects:
            project_root = portfolio / project.path
            project_name = None if project.path == Path(".") else project.name
            for scope in discover_scopes(project_root):
                if project_name:
                    full_scope = ScopePath(Path(project_name) / scope)
                else:
                    full_scope = scope
                all_written.extend(materialize(full_scope, store, portfolio, config.materializer))
        for spec in config.materializer.views:
            all_written.extend(materialize_view(spec, store, portfolio, config.materializer))
    elif args.scope:
        scope = ScopePath(args.scope)
        all_written.extend(materialize(scope, store, portfolio, config.materializer))
    else:
        scope = ScopePath(Path("."))
        all_written.extend(materialize(scope, store, portfolio, config.materializer))

    for p in all_written:
        print(p)


def _cmd_check(args: argparse.Namespace, config) -> None:
    from context_kernel.freshness_gate import check

    portfolio = config.portfolio_root
    store = _build_store(portfolio)
    check(args.path.resolve(), store, portfolio, config)


def _cmd_mcp(args: argparse.Namespace, config) -> None:
    from context_kernel.orientation_server import serve

    portfolio = config.portfolio_root
    store = _build_store(portfolio)
    embedder_key = _resolve_api_key(config.ingester.embedder_api_key_env)
    embedder = _build_embedder(config, embedder_key)
    serve(portfolio, store, config.orientation, embedder=embedder)


if __name__ == "__main__":
    sys.exit(main())
