# Nano Runtime Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound AI Recruiter memory usage so the existing product can be validated on a 512 MiB Lightsail Nano without removing capabilities.

**Architecture:** Replace archive materialization with a file-backed, incremental iterator; keep API/worker contracts intact; add deploy-time low-memory settings and an idempotent Nano host profile. Heavy document parsers become lazy imports so API startup does not pay worker-only memory cost.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, boto3/S3, SQS, PostgreSQL, Docker, GitHub Actions, Bash.

**Spec:** `docs/superpowers/specs/2026-09-12-nano-runtime-design.md`

## Global Constraints

- Keep PDF, DOCX and ZIP imports.
- Keep 500 CVs per batch, 15 MiB per document, 500 MiB per ZIP, and 1 GiB expanded-batch limits.
- Keep automatic Bedrock ingestion, evaluation and ranking.
- Keep durable SQS retry/DLQ and tenant isolation behavior unchanged.
- Nano production values: `IMPORT_EVALUATION_CONCURRENCY=1`, `PG_POOL_SIZE=2`, `PG_MAX_OVERFLOW=2`.
- Add 2 GiB swap as a safety net; do not use swap to justify archive materialization.

---

### Task 1: Stream S3 archives to a file-backed object

**Files:**
- Modify: `app/infrastructure/imports/storage.py`
- Test: `app/tests/test_candidate_import_infrastructure.py`

**Interfaces:**
- Produces: `download_staging_object_to_file(key: str, fileobj) -> int`
- Existing `read_staging_object(key: str) -> bytes` remains for individual <=15 MiB documents.

- [ ] **Step 1: Write failing storage test**

Add a test with a fake S3 body whose `read()` records requested chunk sizes. Assert `download_staging_object_to_file()` repeatedly reads bounded chunks, writes the same payload to a seekable file, rewinds it to position 0, and returns byte count.

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py -q`
Expected: FAIL because `download_staging_object_to_file` does not exist.

- [ ] **Step 3: Implement bounded download**

Implement with a constant such as `STREAM_CHUNK_BYTES = 1024 * 1024`:

```python
def download_staging_object_to_file(key: str, fileobj) -> int:
    response = _s3_client().get_object(Bucket=get_import_staging_bucket(), Key=key)
    body = response["Body"]
    total = 0
    while True:
        chunk = body.read(STREAM_CHUNK_BYTES)
        if not chunk:
            break
        fileobj.write(chunk)
        total += len(chunk)
    fileobj.seek(0)
    return total
```

- [ ] **Step 4: Run storage tests**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "perf: stream candidate import staging downloads"`

### Task 2: Convert ZIP expansion to incremental iteration and lazy parsers

**Files:**
- Modify: `app/infrastructure/imports/documents.py`
- Modify: `app/tests/test_candidate_import_documents.py`

**Interfaces:**
- Replace archive input contract with `iter_zip_documents(fileobj, *, remaining_documents: int, remaining_bytes: int) -> Iterator[ExpandedDocument]`.
- `ExpandedDocument` still carries only one child payload at a time.
- `extract_document(data: bytes, filename: str) -> ParsedDocument` remains unchanged.

- [ ] **Step 1: Write failing iterator tests**

Add tests that create a temporary ZIP file, consume the iterator one child at a time, and assert existing security/limit exceptions still fire. Add a regression test proving the result is an iterator/generator rather than a prebuilt list.

- [ ] **Step 2: Run document tests to verify failure**

Run: `python -m pytest app/tests/test_candidate_import_documents.py -q`
Expected: FAIL because `iter_zip_documents` does not exist.

- [ ] **Step 3: Implement incremental ZIP iterator**

Open `zipfile.ZipFile(fileobj, "r")`, validate each `ZipInfo`, update cumulative counters before extraction, read only the current entry, `yield ExpandedDocument(...)`, then release the local payload on the next iteration. Preserve traversal, symlink, nested archive, encryption, count, per-document and expanded-byte checks.

- [ ] **Step 4: Make heavy parser imports lazy**

Remove module-level `import fitz` and `from docx import Document`; import them inside `_extract_pdf_text` and `_extract_docx_text` respectively. No public behavior changes.

- [ ] **Step 5: Run document tests**

Run: `python -m pytest app/tests/test_candidate_import_documents.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -am "perf: iterate zip candidate documents incrementally"`

### Task 3: Make worker archive expansion file-backed and checkpoint-safe

**Files:**
- Modify: `app/workers/candidate_imports.py`
- Modify: `app/tests/test_candidate_import_worker.py`

**Interfaces:**
- Consumes: `storage.download_staging_object_to_file()` and `documents.iter_zip_documents()`.
- Archive is marked `COMPLETED` only after the iterator exhausts and every yielded child has been staged/persisted.

- [ ] **Step 1: Write failing worker test**

Use a fake archive downloader and generator with two children. Assert first child is written/persisted before the generator yields the second, and assert archive completion occurs only after generator exhaustion. Add failure case where second child raises and archive remains non-completed.

- [ ] **Step 2: Run worker tests to verify failure**

Run: `python -m pytest app/tests/test_candidate_import_worker.py -q`
Expected: FAIL against the current `read_staging_object` + list implementation.

- [ ] **Step 3: Implement file-backed archive processing**

Use `tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")` (or an equivalent named temporary file) as the S3 destination. Reject a downloaded byte count over `MAX_ARCHIVE_BYTES`. Iterate children and write each staging object immediately; do not collect child payloads in a list. Keep only lightweight ORM child references/counters required for the final checkpoint.

- [ ] **Step 4: Run candidate import worker suites**

Run: `python -m pytest app/tests/test_candidate_import_worker.py app/tests/test_candidate_import_resume.py app/tests/test_candidate_import_ingestion_worker.py app/tests/test_candidate_import_evaluation_worker.py app/tests/test_candidate_import_ranking_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -am "perf: bound candidate import archive memory"`

### Task 4: Add Nano runtime and host profile

**Files:**
- Create: `scripts/configure-nano-host.sh`
- Modify: `app/tests/test_deploy_contract.py`
- Modify: `app/tests/test_candidate_import_deploy.py`
- Modify: `scripts/deploy-api.sh`
- Modify: `scripts/deploy-worker.sh`
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Production exports `IMPORT_EVALUATION_CONCURRENCY=1`, `PG_POOL_SIZE=2`, `PG_MAX_OVERFLOW=2`.
- `configure-nano-host.sh` is idempotent and creates 2 GiB swap only if equivalent swap is absent, configures Docker log rotation, and applies conservative PostgreSQL settings without recreating the database.

- [ ] **Step 1: Add failing deployment-contract tests**

Assert deploy workflow/scripts contain concurrency `1`, PG pool variables, and post-verification image pruning. Assert host script contains guarded `fallocate`/`mkswap`/`swapon`, `/etc/docker/daemon.json` rotation (`max-size` and `max-file`), and low-memory PostgreSQL settings.

- [ ] **Step 2: Run deployment contract tests**

Run: `python -m pytest app/tests/test_deploy_contract.py app/tests/test_candidate_import_deploy.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `configure-nano-host.sh`**

Use strict Bash mode. Configure `/swapfile` to 2 GiB only when needed; persist it in `/etc/fstab`; set `vm.swappiness=10`; merge/write Docker daemon json with `json-file` log rotation; detect the installed PostgreSQL config path and set conservative values such as `shared_buffers=64MB`, `work_mem=2MB`, `maintenance_work_mem=32MB`, `effective_cache_size=192MB`, `max_connections=20`; restart only services whose config changed; print `free -h`, `swapon --show`, Docker logging configuration and selected PostgreSQL settings.

- [ ] **Step 4: Pass Nano env through API and worker containers**

Add `PG_POOL_SIZE` and `PG_MAX_OVERFLOW` to both deploy scripts and set workflow production values to `2`/`2`; change production evaluation concurrency from `3` to `1`.

- [ ] **Step 5: Add post-success image cleanup**

After API/worker/frontend verification succeeds, execute a conservative `docker image prune -f` (not `docker system prune`) so unused layers/images are removed while running images and tagged rollback images remain available.

- [ ] **Step 6: Run deployment tests**

Run: `python -m pytest app/tests/test_deploy_contract.py app/tests/test_candidate_import_deploy.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

`git commit -am "ops: add nano runtime deployment profile"`

### Task 5: Verify full regression suite

**Files:**
- No production changes unless a regression is found.

- [ ] **Step 1: Run backend tests**

Run: `python -m pytest app/tests/ -q`
Expected: PASS.

- [ ] **Step 2: Run frontend checks**

Run from `frontend-react`: `npm ci && npm run lint && npx vitest run && npm run build`
Expected: PASS.

- [ ] **Step 3: Run PostgreSQL/contract CI through the PR workflow**

Create a draft PR from `optimization/nano-runtime` into `main` and require all PR workflow jobs to pass.

- [ ] **Step 4: Review memory-sensitive invariants**

Verify by code review that archives are never read wholly through `read_staging_object`, expanded children are not accumulated, concurrency is 1 in production, pool is 2+2, and host swap/log rotation is idempotent.

- [ ] **Step 5: Mark PR ready only after green CI**

Do not merge as part of this plan until the user explicitly asks for merge.