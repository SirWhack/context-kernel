<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: 286e033d3d25ab244b674ab60d936ae4653bf9ed50e247b56d465e011b0a7b4a
materialized: 2026-05-27T21:35:43Z
-->

The context_kernel scope is the entry point and orchestration layer for the `ck` command-line tool. Its primary responsibility is to parse user commands, load project configuration, and dispatch work to the three core subsystems: the Ingester (which processes source code into a knowledge graph), the Materializer (which renders views from that graph), and the FreshnessGate (which enforces that reads never return stale data). The scope also owns structured logging, an operational journal for audit trails, and cross-module type definitions.

The public API surface is centered on `agent_cli.main()`, which accepts an optional `argv` list and returns an integer exit code. It builds an `argparse.ArgumentParser` with subcommands `ingest`, `materialize`, `check`, and `mcp`, each dispatched to a private `_cmd_*` function. Configuration is loaded via `config_store.load()`, which reads a `.context-kernel/config.toml` file and returns a `Config` dataclass containing `IngesterConfig`, `MaterializerConfig`, `OrientationConfig`, a `portfolio_root` path, and a list of `ProjectSpec` entries. The `freshness_gate.check()` function is the read-boundary enforcer: it compares a file’s freshness header against the current source tree hash and regenerates content if stale, raising `StaleReadError` only on regeneration failure.

Internally, the scope is organized into several focused modules. `config_store.py` defines the configuration dataclasses and the `load()` function that parses TOML with defaults. `logging.py` provides `configure()` and `invocation_id` (a `contextvars.ContextVar`), using either `_JsonFormatter` or `_HumanFormatter` depending on the log format. `operational_journal.py` defines `JournalEntry` (a dataclass with invocation metadata) and `append()` for writing structured entries to `log.md`. `types.py` holds domain primitives like `ViewSpec` (a materializer view configuration), `LLMMetrics` (a thread-safe accumulator for LLM call metrics with cost estimation), and type aliases `GraphCommit`, `Sha256`, and `ScopePath`. The `freshness_gate.py` module depends on `KnowledgeStore` (a protocol from the graph subsystem) and `source_tree_hash` from the ingester, using the materializer’s header parser to extract freshness metadata.

The scope depends on the `graph/`, `ingester/`, and `materializer/` subsystems for actual work, importing their protocols and functions rather than concrete implementations. It also uses standard library modules (`argparse`, `logging`, `pathlib`, `tomllib`, `uuid`, `contextvars`) and the `datetime` module. The design follows a command-pattern dispatch in the CLI, a configuration-object pattern for passing settings, and a protocol-based boundary for the knowledge store to keep the freshness gate decoupled from any specific storage backend.

## Recommended documentation

This scope has 32 code entities across 1 files but no reference documentation. To create one: `/init-reference context_kernel`

