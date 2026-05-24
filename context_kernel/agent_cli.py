"""AgentCLI — `ck` entrypoint. Dispatches to other modules. See ARCHITECTURE.md §2.6."""

import sys

# Does not own:
#   - interactive prompts during long operations (batch-mode only)
#   - authentication / access control (runs as local user)
#   - cross-host coordination (single-host)
#   - atomic multi-command sequences (each `ck` call is independent)


def main(argv: list[str] | None = None) -> int:
    """Parse args; dispatch to `ingest` / `materialize` / `check` / `mcp`. Return a structured exit code."""
    raise NotImplementedError("TODO(impl)")


if __name__ == "__main__":
    sys.exit(main())
