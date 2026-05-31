# Kernel-vs-grep on the vibecoded corpus: locate_anything_setup & sudoku

**Date:** 2026-05-30
**Branch:** eval/kernel-vs-grep-harness
**Corpus:** first two repos from `test-repos/vibe-coded/` (see PROVENANCE.md) — the
contrast arm the campaign had not yet tested. Both are Claude-Code-built, low-star. This
is the corpus the kernel is *supposed* to help with (thin doc layer), per the
"eval-corpus-must-be-vibecoded" thesis. (locate carries a real project doc set under
`docs/`; sudoku is doc-light — that difference turns out to matter, see finding 3.)

## Setup

Per-repo standalone kernel (no `[[projects]]` block — mirror open-webui's config; a
`path = "."` project trips `ValueError: Project path resolves to empty name`). Local
embedder :8081 (qwen3-0.6b), cloud DeepSeek summarizer. Ingest → materialize → harness
(`run_eval.py --repo vibe-coded/<r> --taskset <r>`), 6 curated questions/repo, gold
hand-verified by opening every file.

| repo | entities | edges | handled types | NOT handled (no handler) |
|------|----------|-------|---------------|--------------------------|
| locate_anything_setup | 554 | 254 | py, md | **rust (.rs)**, sh |
| sudoku | 326 | 94 | py, ts, tsx, md | **terraform (.tf)**, graphql, yml |

Tool isolation verified clean on all four arms (kernel: only `mcp__ck__find`/`overview`/
`Read`; grep: only `Read`/`Bash`/`Grep`/`Glob`). No escape-hatch tools fired.

## Results

**locate_anything_setup** (Rust axum WS server + Python LocateAnything-3B sidecar)

| arm | calls | failed | dup | halluc | recall | grounded |
|-----|-------|--------|-----|--------|--------|----------|
| kernel | 38 | 2 | 4 | 1 | 13/16 | 15/16 |
| grep | 16 | 0 | 0 | 2 | 15/16 | 16/16 |

**sudoku** (Python Starlette/Ariadne-GraphQL on Lambda + React/Apollo web + Terraform)

| arm | calls | failed | dup | halluc | recall | grounded |
|-----|-------|--------|-----|--------|--------|----------|
| kernel | 27 | 0 | 1 | 1 | 12/18 | 10/18 |
| grep | 27 | 0 | 0 | 1 | 13/18 | 17/18 |

## Findings

**1. Grep matched or beat the kernel on both repos.** locate: grep hit near-perfect
grounding in 16 calls; the kernel needed 38 (2 failed + 4 dup) to reach parity. sudoku:
equal cost (27 each), but grep grounded 17/18 vs the kernel's 10/18. No win for the
kernel on either repo.

**2. The kernel's entire deficit is ingest *coverage*, not retrieval quality.** Where the
graph has handlers (Python, TS/TSX), the arms tie — locate Q2/Q5/Q6 and sudoku
Q1/Q2/Q5 are dead even. The gap is concentrated 100% in file types with no handler:
  - sudoku **Q6 (infra): kernel 0/4 grounded, grep 4/4.** The kernel arm reached *zero*
    `terraform/*.tf` or `deploy.yml` files; grep read all ten terraform files + the
    workflow. Terraform is structurally invisible to `find` (no entities) **and** to
    `overview` (no scope summary).

**3. `overview` can rescue an unhandled language — but only when an *in-graph* file names
it.** This is what separates the two repos (verified by grep, not raw file counts):
  - **locate's in-graph docs name the Rust components.** `ARCHITECTURE.md` /
    `CLIENT_PROTOCOL.md` / `OPERATIONS.md` / `SECURITY.md` reference the Rust server, so
    the Rust paths live in the graph via the docs; the kernel arm read
    `main.rs`/`ws.rs`/`ipc.rs`/`config.rs`/`prompt_validator.rs` through `overview`
    despite zero Rust entities.
  - **sudoku has nothing in-graph naming terraform** (grep over api/, web/src/, README
    for `terraform`/`.tf` → empty), so the infra subsystem was unreachable. → The
    kernel's polyglot coverage is a **doc↔code corpus property** (a handled file must name
    the code), the same property identified for doc↔code linking — now demonstrated on the
    grounding/coverage axis.

**4. Secondary: the kernel under-explores siblings.** sudoku Q3 (data layer, all Python,
fully in-graph): kernel grounded 1/4 (read only `sudoku_games.py`), grep 4/4. Once
`find` returns one strong hit the arm stops; grep's habit of listing the directory and
reading every sibling catches the whole set. A retrieval/agent-prompt issue, not a
coverage one.

## Implication for the roadmap

The lever on the vibecoded corpus is **language-handler coverage**, not graph
traversal/expansion. ADR-0023 neighbor expansion still has nothing to prove here: the
missing nodes (terraform, rust) aren't one hop away in the graph — they're absent
entirely. Before expansion can matter on these repos, the ingester needs handlers for
the languages vibecoded polyglot repos actually use (Terraform, Rust, GraphQL SDL,
CI YAML), OR the doc layer must name them (which doc-light vibecoded repos won't do).

This is the first eval round where the kernel was tested on its intended corpus and the
result is honest: **competitive only where it has coverage; blind where it doesn't, and
vibecoded repos are exactly where coverage is thinnest.**

Transcripts: `evals/runs/sessions/{locate_anything_setup,sudoku}/` (gitignored).
