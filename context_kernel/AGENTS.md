<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: f0175cf8faafe4a8b58eb59942715a94876454eb2f53c5b2b7ab91707734f584
materialized: 2026-05-27T21:06:01Z
-->

The context_kernel scope is the entry point and orchestration layer for the `ck` command-line tool. Its primary responsibility is to parse user commands, load project configuration, and dispatch to the appropriate subsystem — the Ingester, Materializer, FreshnessGate, or OrientationServer — while enforcing system invariants like structured logging and an append-only operational journal. The scope does not contain the core graph, ingestion, or materialization logic itself; instead, it wires those subsystems together and provides the CLI surface that drives them.

The public interface is centered on `agent_cli.main()`, which accepts an optional `argv` list and returns a structured exit code. It builds an `argparse.ArgumentParser` and dispatches to private handlers (`_cmd_ingest`, `_cmd_materialize`, `_cmd_check`, `_cmd_mcp`, `_cmd_init`) based on the subcommand. Configuration is loaded by `config_store.load()`, which reads a `.context-kernel/config.toml` file and returns a `Config` dataclass containing `IngesterConfig`, `MaterializerConfig`, `OrientationConfig`, and a list of `ProjectSpec` objects. The `freshness_gate.check()` function provides a critical invariant enforcement point: it compares a file’s freshness header against the current source tree hash and regenerates content if stale, raising `StaleReadError` only on regeneration failure.

Internally, the scope is organized into several focused modules. `config_store.py` defines the configuration dataclasses and the `load()` function, using `tomllib` for parsing. `logging.py` provides `configure()` and `invocation_id` (backed by a `contextvars.ContextVar`), with two formatters (`_JsonFormatter` and `_HumanFormatter`) selected at configuration time. `operational_journal.py` defines the `JournalEntry` dataclass and an `append()` function that writes structured entries to a log file. `types.py` holds cross-module primitives like `ViewSpec`, `LLMMetrics` (a thread-safe accumulator with `record_chat`, `record_embed`, and `estimated_cost_usd` methods), and type aliases `GraphCommit`, `Sha256`, and `ScopePath`. The `freshness_gate.py` module depends on `KnowledgeStore` (a protocol from the graph subpackage) and the ingester’s `source_tree_hash` function, using them to implement its stale-read check.

This scope depends on several sibling subpackages: `context_kernel.graph` (for the `KnowledgeStore` protocol), `context_kernel.ingester` (for change detection and source tree hashing), `context_kernel.materializer` (for header parsing), and `context_kernel.orientation_server` (for the MCP command). It also imports standard library modules (`argparse`, `logging`, `pathlib`, `tomllib`, `dataclasses`, `contextvars`, `uuid`) and uses `typing.TYPE_CHECKING` to avoid circular imports in `freshness_gate.py`. The overall architecture follows a command-dispatch pattern where `agent_cli.main()` acts as the router, `config_store` provides the configuration context, and each subcommand delegates to a dedicated subsystem.

## Recommended documentation

This scope has 32 code entities across 1 files but no reference documentation. To create one: `/init-reference context_kernel`

