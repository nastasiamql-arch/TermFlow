# TermFlow Ten-Part Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search SOURCE with ten parallel Prompt A requests, show progress, combine validated results safely, and export one UTF-8 file.

**Architecture:** A pure chunking module creates ten ordered source ranges with overlap. A pure batch module owns task status, validation, retries, aggregation, and conflict candidates. The PySide6 main window runs those tasks off the UI thread, reports per-chunk progress, and only enables the existing review/polish flow after all chunks validate and conflicts are resolved.

**Tech Stack:** Python 3.12+, PySide6, httpx, Pydantic, pytest, PyInstaller, Inno Setup, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-05-ten-part-search-design.md`

## Global Constraints

- Prompt A remains exact and unchanged for every chunk request.
- VOCAB remains READ-ONLY; never write SOURCE or VOCAB.
- Every chunk response passes STEP A strict validation before aggregation.
- UPDATE rows are never sent to STEP B automatically.
- Identical overlap rows may be deduplicated; conflicting rows are always presented for user choice.
- Incomplete or cancelled batches never become final results or go to STEP B.
- API keys never enter history, logs, or request snapshots.

---

### Task 1: Source chunking

**Files:**
- Create: `src/termflow/core/search_chunks.py`
- Create: `tests/test_search_chunks.py`

**Interfaces:**
- Produces `SourceChunk(index: int, core_start: int, core_end: int, request_start: int, request_end: int, text: str)` and `split_source(source: str, count: int = 10, overlap_units: int = 1) -> list[SourceChunk]`.
- `core_start/core_end` partition the source without overlap; `request_start/request_end` include neighbor context.

- [x] Write failing tests for ten ordered chunks, complete non-overlap core coverage, overlap at boundaries, preserved Unicode/CRLF, paragraph-first boundaries, line fallback, one-line fallback, and empty/short sources.
- [x] Run `F:\Temp\termflow-build-venv\Scripts\python.exe -m pytest tests/test_search_chunks.py -q` and confirm the missing module fails collection.
- [x] Implement paragraph and line boundary discovery, balanced target offsets, Unicode-safe fallback offsets, and explicit empty/short input behavior.
- [x] Run the focused tests and verify concatenating core slices reproduces SOURCE exactly and every request slice includes its core slice.
- [x] Run `F:\Temp\termflow-build-venv\Scripts\ruff.exe check src/termflow/core/search_chunks.py tests/test_search_chunks.py`.
- [x] Commit as `feat: split source into ten search chunks`.

### Task 2: Batch state, strict per-chunk results, and aggregation

**Files:**
- Create: `src/termflow/core/search_batch.py`
- Create: `tests/test_search_batch.py`

**Interfaces:**
- `ChunkStatus` values are `pending`, `running`, `validating`, `retrying`, `complete`, `failed`, and `cancelled`.
- `ChunkRun` stores its `SourceChunk`, status, retries, raw response, parsed NEW/UPDATE rows, and error text.
- `SearchBatch` owns ten runs, supports `mark_running`, `mark_validating`, `accept_response`, `fail_chunk`, `retry_chunk`, `cancel_pending`, and `aggregate`.
- `aggregate` returns ordered unique rows and conflicts containing all `(chunk_index, category, row)` candidates; it never chooses a candidate.

- [x] Write failing tests for state transitions, validating every raw response through `validate_step_a`, failed-chunk retry without dropping completed results, cancellation, and incomplete-batch blocking.
- [x] Write failing aggregation tests for exact overlap duplicates, source-order preservation, same-CN conflicts within/between categories, and keeping every conflicting candidate.
- [x] Run `F:\Temp\termflow-build-venv\Scripts\python.exe -m pytest tests/test_search_batch.py -q` and confirm expected failures.
- [x] Implement typed batch/result models and deterministic aggregation sorted by chunk index then row order.
- [x] Make aggregate readiness false until ten non-empty tasks are valid and all conflicts are resolved; mark empty source portions as skipped-complete without sending blank API requests.
- [x] Run focused tests and `F:\Temp\termflow-build-venv\Scripts\ruff.exe check src/termflow/core/search_batch.py tests/test_search_batch.py`.
- [ ] Commit as `feat: aggregate validated multi-part search results`.

### Task 3: Cancellable provider backoff for request bursts

**Files:**
- Modify: `src/termflow/ai/service.py`
- Modify: `tests/test_ai_service.py`

**Interfaces:**
- Existing `HTTPProvider.generate(request)` remains the public provider API.
- Retry delay is exponential, cancellation-aware, and applies to existing retriable status/timeouts without logging credentials.

- [ ] Add tests for 429/5xx retry delay progression, no retry on non-retriable status, and cancellation during backoff.
- [ ] Run `F:\Temp\termflow-build-venv\Scripts\python.exe -m pytest tests/test_ai_service.py -q` and confirm new tests fail before implementation.
- [ ] Implement bounded exponential backoff using the provider cancellation event so cancellation interrupts the wait promptly.
- [ ] Run the AI service tests and lint.
- [ ] Commit as `fix: back off and cancel provider retries safely`.

### Task 4: Background ten-request coordinator and progress UI

**Files:**
- Create: `src/termflow/ui/search_progress.py`
- Modify: `src/termflow/main.py`
- Modify: `src/termflow/ai/base.py` only if a typed cancellation hook is needed.
- Create: `tests/test_search_coordinator.py`

**Interfaces:**
- `MultiSearchWorker` creates one configured provider and `GenerateRequest` per active chunk, with exact prompt text, identical VOCAB, chunk SOURCE, and a chunk-number wrapper.
- Worker signals carry `(chunk_index, status, message, counts)`; completion carries one `SearchBatch`.
- `SearchProgressDialog` displays overall `X/10`, ten per-chunk rows, Cancel, and retry controls for failed chunks.

- [ ] Write tests with fake providers that prove ten distinct SOURCE fragments, identical Prompt/VOCAB values, max concurrency ten, progress for each chunk, and cancellation fan-out.
- [ ] Run the coordinator tests and confirm missing worker behavior fails.
- [ ] Implement worker orchestration using futures in the background QThread; emit signals only through Qt signals and never block the GUI thread.
- [ ] Add retry of failed chunks while preserving completed `ChunkRun` objects; apply provider retry backoff from Task 3.
- [ ] Add a progress dialog with Thai status labels, per-chunk NEW/UPDATE counts, overall progress, Cancel, and Retry Failed Chunks.
- [ ] Change `Run Search` to start the ten-part path; disable search/polish/export controls during active work and restore them on completion/cancel.
- [ ] Run coordinator tests, existing tests, and Ruff.
- [ ] Commit as `feat: run ten search chunks with live progress`.

### Task 5: Resolve conflicts, copy/export one combined result, and record history

**Files:**
- Create: `src/termflow/ui/search_conflicts.py`
- Modify: `src/termflow/main.py`
- Modify: `src/termflow/core/history.py` only if a batch-specific helper is needed.
- Modify: `tests/test_search_batch.py`
- Create: `tests/test_search_export.py`

**Interfaces:**
- `ConflictResolutionDialog` returns explicit user choices keyed by `(category, CN)`.
- `format_step_a_result(new_rows, update_rows) -> str` emits the two Prompt A headers and real tab-delimited rows, using the no-list marker for empty categories.
- One completed batch snapshot stores the exact prompt metadata and, per chunk, offsets/hash/raw/parsed/validation/retry/status. It stores no key or full settings secrets.

- [ ] Add tests for unresolved conflicts blocking output, chosen candidate yielding unique CNs, and combined NEW/UPDATE copy text.
- [ ] Add a read-only file test proving SHA-256, size, and mtime of SOURCE/VOCAB stay unchanged through chunking, batch completion, cancellation, and export.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Implement conflict resolution that requires the user to choose one complete candidate row and category; never merge fields automatically.
- [ ] Integrate combined tables into existing review UI; only allow selected NEW rows to polish after batch complete and conflict resolution.
- [ ] Add `บันทึกผลรวม` using `QFileDialog` and UTF-8 atomic write to the chosen new output path; never default to SOURCE or VOCAB path.
- [ ] Save one atomic history record with each chunk's raw response and validation evidence; verify API keys are absent.
- [ ] Run relevant tests, existing suite, and Ruff.
- [ ] Commit as `feat: review and export combined search results`.

### Task 6: Release documentation, version, and Windows package

**Files:**
- Modify: `README.md`
- Modify: `src/termflow/version.py`
- Modify: `pyproject.toml`
- Modify: `installer/TermFlow.iss`
- Existing release workflow: `.github/workflows/release.yml`

- [ ] Document ten-part search, concurrent progress, retry/cancel, conflict selection, API usage, and single-file export in Thai-first user instructions.
- [ ] Bump version to `1.0.5` consistently in version source, project metadata, and installer fallback version.
- [ ] Run full tests with `F:\Temp\termflow-build-venv\Scripts\python.exe -m pytest -q` and lint with `F:\Temp\termflow-build-venv\Scripts\ruff.exe check src tests`.
- [ ] Build with `powershell -ExecutionPolicy Bypass -File scripts/package.ps1`, run `dist\TermFlow.exe --check-prompts`, and verify installer output plus SHA-256 sidecar.
- [ ] Commit as `feat: release ten-part search workflow` and tag `v1.0.5` only after local build and tests pass.
- [ ] Push branch/tag, wait for GitHub Actions release success, download both release assets, and verify the installer SHA-256 matches the sidecar.
