<!-- context-kernel-freshness
graph: ce4c30de6021574f8be593ca3ef2c62ccfde5e39118e774477c1d6d76f0f9abe
source-tree: d752848a672c1e5a8acd3c36e2ea6de37530a670f4d415f9818478908fbca60a
materialized: 2026-06-01T01:08:19Z
-->

This scope provides the cloud-native deployment and execution layer for the Context Kernel ingestion pipeline, specifically targeting the Modal serverless platform. Its primary responsibility is to take the local development pipeline (which clones repositories, runs `ck ingest` and `ck materialize`, and syncs results) and make it run reliably in the cloud, triggered by GitHub push webhooks. The scope acts as the bridge between a Cloudflare Worker (the webhook receiver) and the Modal runtime, handling authentication, state persistence, and environment configuration.

The public API surface is minimal and focused. The `ingest(body: dict)` function is the main webhook entry point, called by the Cloudflare Worker with a payload containing GitHub App credentials and repository metadata. Internally, `ingest` orchestrates the pipeline by calling `get_installation_token()` to exchange GitHub App credentials for an installation token, then `clone_repos()` to pull all portfolio repositories into a Modal volume. The `write_config()` function generates a `config.toml` from environment variables, and `run_pipeline()` executes the actual `ck ingest` and `ck materialize` commands. State persistence is handled by `restore_state()` and `save_state()`, which copy data between the Modal volume (`state_volume`) and the local workspace directory. The `test_ingest()` function provides a local smoke test path via `modal run`.

The scope depends entirely on the Modal SDK for serverless execution, volumes, and web endpoint creation. It imports `modal` for the `app`, `image`, and `state_volume` objects, and uses standard library modules (`json`, `os`, `shutil`, `subprocess`, `time`) for filesystem operations and subprocess management. The `spike.py` module is a minimal validation script that verifies Modal deployment, web endpoints, and volume access work correctly, serving as a quick health check rather than a production component. The design follows a straightforward procedural pattern: a single entry point function (`ingest`) that calls a sequence of helper functions, with state managed through Modal volumes for persistence across cold starts.

## Recommended documentation

This scope has 12 code entities across 1 files but no reference documentation. To create one: `/init-reference modal`

