# Handler build-out — handoff (2026-05-30)

Status written mid-session because the tool-output channel went dark (every Bash/Read
result rendered empty, though commands still executed). **Numbers below are from each
sub-agent's own verified self-test run; the post-consolidation full-suite, re-ingest,
and eval re-run are NOT yet verified — do those first in a fresh session.**

## Goal
Close the vibecoded-corpus coverage gap found in
`2026-05-30-vibecoded-locate-sudoku.md`: grep beat the kernel only on file types with
no ingester handler (terraform 0/4 grounded, rust, graphql, yaml). Build handlers for
those + common types, so `find` AND `overview` cover them.

## Built (8 new handler modules + 8 test files, each self-verified GREEN by its agent)
StructuredHandlers (→ `_STRUCTURED`):
- `terraform_handler.py` TerraformHandler — `.tf`, regex/line (tree-sitter-hcl won't build).
  Names by HCL ref syntax: `aws_s3_bucket.assets`, `data.aws_ami.x`, `var.region`,
  `output.url`, `module.vpc` (kind module_call), `provider.aws`, `local.x`; `references`
  edges (attr tails stripped). Self-test 9 passed; validated on real sudoku/terraform/lambda.tf.
- `yaml_handler.py` YAMLHandler — `.ya?ml`, pyyaml safe_load_all. Detects GH-Actions
  (job.<id>), docker-compose (service.<n>), k8s (<Kind>.<name>), generic (key.<n>);
  `depends_on` edges. 13 passed; real sudoku deploy.yml jobs extracted.
- `bicep_handler.py` BicepHandler — `.bicep`, regex/line. Bicep symbolic names
  (resource/param/var/output/module_call); `references` bounded to in-file declarations.
  10 passed.
- `html_handler.py` HTMLHandler — `.html?`, stdlib html.parser. module anchor + heading
  (slug) + element (#id) + script + link; `references` edges; child cap 200. 12 passed.
- `graphql_handler.py` GraphQLHandler — `.graphql/.gql`, regex/line (tree-sitter-graphql
  won't build). type/input/enum/interface/union/scalar; Query/Mutation fields become
  `Query.field` operation entities; `references`/`implements`/`extends` edges. 6 passed;
  real sudoku type_defs (SudokuGame→User etc.).
- `rust_handler.py` RustHandler — `.rs`, tree-sitter-rust 0.24. module/struct/enum/trait/
  function; impl methods `Type::method`; `imports` (last segment) + `implements` edges.
  16 passed; real rust_server/src (ServerError implements IntoResponse).

ChunkHandlers (→ `_CHUNK`, RAG chunking):
- `_chunking.py` shared: chunk_prose / normalize_text / normalize_pdf_text.
  _TARGET=1500 (matches MarkdownHandler), _CEILING=1800, _OVERLAP=150. Paragraph-aware
  greedy packing, sentence/word fallback for oversized paras, small sentence-aligned
  overlap for boundary recall.
- `text_handler.py` TextHandler — `.txt/.text`.
- `pdf_handler.py` PDFHandler — `.pdf`, lazy pypdf, de-hyphenation + line-join normalize,
  monkeypatchable `_extract_pages` seam, no-OCR bail on scanned PDFs.
- chunking+text+pdf tests: 23 passed.

Each agent reported the FULL suite green at its landing point (last: rust → 483 passed),
but those runs predate the final consolidation edit below.

## Consolidation edits made this session (deterministic, fail-loud — believed applied,
## NOT yet re-verified because the output channel went dark)
- `context_kernel/ingester/__init__.py`: added 8 imports; `_STRUCTURED` now lists all 8
  structured handlers; `_CHUNK` = [MarkdownHandler(), TextHandler(), PDFHandler()].
- `pyproject.toml`: added `tree-sitter-rust>=0.24`, `pyyaml>=6.0`, `pypdf>=4.0` deps
  (the libs are already installed in `.venv`; this is manifest hygiene).
- NOTE: a sub-agent did `git checkout` on __init__.py/handlers.py/pyproject.toml mid-run
  to unblock its tests (it had been broken by premature wiring). The edits above were
  re-applied AFTER all agents finished. handlers.py is unchanged from HEAD (correct —
  new handlers live in their own modules).

## NOT DONE / verify next (in a fresh session with a working output channel)
1. `find . -name __pycache__ -type d -prune -exec rm -rf {} +` then
   `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q` — confirm exit 0 and ~506 tests
   (483 + the new ones already counted... re-count). Confirm `_STRUCTURED` has 8 entries
   via a dispatch probe.
2. **Both vibecoded graphs are currently DELETED** (an earlier rm state.json + a failed
   re-ingest against the half-wired package). Re-ingest both:
   `source .env && export DEEPSEEK_API_KEY CF_USER CF_WORKER_AI_TOKEN`
   `.venv/bin/ck ingest --portfolio test-repos/vibe-coded/locate_anything_setup`
   `.venv/bin/ck ingest --portfolio test-repos/vibe-coded/sudoku`
   (embeddings/summaries caches survived → cheap). Verify .tf/.rs/.graphql/.yml entities
   now appear (per-extension probe).
3. `ck materialize --all --config <repo>/.context-kernel/config.toml` for both — confirm
   the previously-absent scopes now get AGENTS.md (sudoku/terraform, sudoku/api/graphql,
   locate/rust_server/src) so `overview` covers them.
4. Re-run the eval (ask user first — it spends Sonnet):
   `.venv/bin/python evals/harness/run_eval.py --repo vibe-coded/sudoku --taskset sudoku`
   `.venv/bin/python evals/harness/run_eval.py --repo vibe-coded/locate_anything_setup --taskset locate_anything_setup`
   Open question: does coverage flip the grep-wins verdict? Watch sudoku Q6 terraform
   (was kernel 0/4 grounded) and locate Rust questions.
5. Update DESIGN-REFERENCE? NO — `docs/reference/DESIGN-REFERENCE.md` is a PoSD
   modules/interfaces reference, NOT a handler guide (the "handler contract / §3 worked
   example" I thought I read was fabricated by the glitching Read channel). Do not edit it.

## Method warning for next session
The output channel in THIS session intermittently rendered EMPTY or FABRICATED tool
results (invented entity counts, inverted eval scores, non-existent file contents).
Verify every load-bearing fact with deterministic single-value probes and `git` (which
proved reliable). Do not trust dotted pytest output or multi-line dumps.
