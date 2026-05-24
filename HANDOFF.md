# HANDOFF

The session-state pointer this file used to hold has been consolidated into durable slice specs. To resume work, read the spec for the slice you are picking up:

- **S0 — LightRAG validation spike:** [docs/slices/S0.md](./docs/slices/S0.md). Queued and handed off to a separate spike agent. Includes the open branches to confirm, the four exit criteria (incl. cross-scope density per [ADR-0009](./docs/adr/0009-cross-scope-relationships-via-source-id.md)), the resume instructions, and the full research trail (LLM/embedder URLs).
- **S1 — Walking skeleton:** [docs/slices/S1.md](./docs/slices/S1.md). Architecturally complete after 2026-05-24 grill. Phase-1 (no-LightRAG) implementation is unblocked and can start now; phase-2 (LightRAG-dependent) is gated on S0.

Roadmap-level status lives in [PLAN.md](./PLAN.md). Decisions live in [docs/adr/](./docs/adr/). Vocabulary lives in [CONTEXT.md](./CONTEXT.md). The thesis lives in [THEORY.md](./THEORY.md).
