<!-- context-kernel-freshness
graph: 4828895ec2ab8c46292fc502e3c028e8b68915c679ff81f463cf9148983976a0
source-tree: ed9406e09c15fb32cb332e8d11f10adc1f7d61a01e9e2d78d8ada486a45ac74b
materialized: 2026-05-27T21:03:12Z
-->

This scope contains the test suite for the model-time project, validating every major subsystem through integration and unit tests. It ensures that the ingester, graph addressing, config store, freshness gate, and agent CLI all behave correctly, both in isolation and when wired together. The tests are organized by module, mirroring the production source tree, and rely heavily on pytest fixtures and `tmp_path` for isolated filesystem state.

The conftest provides a session-scoped `embedder` fixture that launches a real `llama-server` subprocess, backing `HttpEmbedder` with a live model for embedding tests. This is the only external service dependency; all other tests use in-memory or temporary filesystem constructs. A private `_reset_ck_logger()` helper prevents logger configuration from leaking between test cases.

The test classes are concrete and focused. `TestArgParsing` and `TestCkInit` in `test_agent_cli.py` exercise the CLI argument parser and `ck init` command via `subprocess` calls. `TestLoadDefaults`, `TestProjectSpec`, and `TestProjectsLoading` in `test_config_store.py` validate TOML loading, default values, and project spec validation rules. `TestFreshnessLogging` in `test_freshness_gate.py` uses a `_FakeStore` that implements the graph store protocol to verify stale-read detection and logging without a real database. `TestHashBytes` and `TestBlobPath` in `test_graph.py` test the deterministic hashing and blob path derivation functions. The largest file, `test_ingester.py`, contains 17 test classes covering Python and TypeScript handler extraction, markdown chunking, change detection, summarizer parsing, blob I/O, project namespacing, and end-to-end ingest flows with and without an embedder.

This scope depends on the full production codebase: `context_kernel.ingester`, `context_kernel.graph`, `context_kernel.config_store`, `context_kernel.freshness_gate`, `context_kernel.agent_cli`, and `context_kernel.materializer`. It also uses `httpx` for the embedder fixture, `pytest` for the test framework, and standard library modules (`subprocess`, `logging`, `pathlib`, `datetime`, `math`, `struct`). The tests are designed to be hermetic—no external network calls except the local `llama-server`—and each test class isolates its state via `tmp_path` or fresh in-memory objects.

## Recommended documentation

This scope has 72 code entities across 1 files but no reference documentation. To create one: `/init-reference tests`

