"""AgentCLI — `ck` entrypoint. Dispatches to other modules. See ARCHITECTURE.md §2.6."""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from context_kernel.config_store import load as load_config
from context_kernel.operational_journal import JournalEntry, append


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
    config = load_config(getattr(args, "config", None))

    invocation_id = uuid4()
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    exit_code = 0

    try:
        if args.command == "init":
            return _cmd_init(args)
        elif args.command == "ingest":
            _cmd_ingest(args, config)
        elif args.command == "materialize":
            _cmd_materialize(args, config)
        elif args.command == "check":
            _cmd_check(args, config)
        elif args.command == "mcp":
            _cmd_mcp(args, config)
    except Exception as exc:
        print(f"ck {args.command}: {exc}", file=sys.stderr)
        exit_code = 1

    duration_ms = int((time.monotonic() - t0) * 1000)
    journal_path = config.portfolio_root / ".context-kernel" / "log.md"
    raw_args = [str(v) for k, v in vars(args).items() if k not in {"command", "config"} and v is not None]
    entry = JournalEntry(
        invocation_id=invocation_id,
        started_at=started,
        command=args.command,
        args=raw_args,
        duration_ms=duration_ms,
        exit_code=exit_code,
        regen_chain=[],
    )
    append(journal_path, entry)
    return exit_code


def _cmd_init(args: argparse.Namespace) -> int:
    portfolio = args.portfolio.resolve()
    git_dir = portfolio / ".git"
    hooks_dir = portfolio / ".githooks" / "pre-commit"
    if not git_dir.exists():
        print("ck init: not a git repository", file=sys.stderr)
        return 1
    if not hooks_dir.exists():
        print(f"ck init: {hooks_dir} not found", file=sys.stderr)
        return 1
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=portfolio,
        check=True,
    )
    print(f"ck init: core.hooksPath set to .githooks in {portfolio}", file=sys.stderr)
    return 0


def _cmd_ingest(args: argparse.Namespace, config) -> None:
    from context_kernel.graph.lightrag_adapter import LightRAGStore
    from context_kernel.ingester import ingest

    portfolio = args.portfolio.resolve()
    store = LightRAGStore(portfolio / ".context-kernel" / "graph")
    ingest(store, portfolio, portfolio, config.ingester)


def _cmd_materialize(args: argparse.Namespace, config) -> None:
    from context_kernel.graph.lightrag_adapter import LightRAGStore
    from context_kernel.ingester.change_detection import discover_scopes
    from context_kernel.materializer import materialize
    from context_kernel.types import ScopePath

    portfolio = config.portfolio_root
    store = LightRAGStore(portfolio / ".context-kernel" / "graph")
    all_written: list[Path] = []

    if args.all_scopes:
        for scope in discover_scopes(portfolio):
            all_written.extend(materialize(scope, store, portfolio, config.materializer))
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
    from context_kernel.graph.lightrag_adapter import LightRAGStore

    portfolio = config.portfolio_root
    store = LightRAGStore(portfolio / ".context-kernel" / "graph")
    check(args.path.resolve(), store, portfolio, config)


def _cmd_mcp(args: argparse.Namespace, config) -> None:
    from context_kernel.graph.lightrag_adapter import LightRAGStore
    from context_kernel.orientation_server import serve

    portfolio = config.portfolio_root
    store = LightRAGStore(portfolio / ".context-kernel" / "graph")
    serve(portfolio, store, config.orientation)


if __name__ == "__main__":
    sys.exit(main())
