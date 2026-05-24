# context_kernel

Code skeleton for Context Kernel. Detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

| Module | Location | ARCHITECTURE.md |
|---|---|---|
| Graph | `graph/` | §2.1 |
| Ingester | `ingester/` | §2.2 |
| Materializer | `materializer/` | §2.3 |
| FreshnessGate | `freshness_gate.py` | §2.4 |
| OrientationServer | `orientation_server/` | §2.5 |
| AgentCLI | `agent_cli.py` | §2.6 |
| ConfigStore | `config_store.py` | §3.1 |
| OperationalJournal | `operational_journal.py` | §3.2 |

Cross-module domain primitives (`GraphCommit`, `Sha256`, `ScopePath`, `ViewSpec`) live in `types.py`.
