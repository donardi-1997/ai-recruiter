# Indeed Resume Ingestion + AI Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Indeed resumes from temporary provider URLs into the existing canonical S3/Bedrock/evaluation/ranking pipeline using durable asynchronous processing on the existing SQS worker.

**Architecture:** Persist one `IndeedResumeIngestion` per Indeed candidate link. Candidate sync records the task and dispatches a typed message on the existing import queue; the existing worker routes the message to an Indeed-specific resumable pipeline that downloads/validates the PDF, writes canonical S3, ingests Bedrock, evaluates the candidate, and materializes ranking. Recruiter CV access uses a new canonical short-lived S3 URL, never the Indeed URL.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, httpx, boto3/S3/SQS/Bedrock, pytest, React/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-15-indeed-resume-ai-ingestion-design.md`

## Global Constraints

- Work only on `feat/indeed-resume-ai-ingestion`.
- `INDEED_ENABLED=false` remains the default.
- Reuse the current candidate-import SQS queue and worker; do not add another AWS queue/service.
- Do not treat an Indeed resume as a manual `ImportBatch`/`ImportItem`.
- Maximum remote resume size is 20 MiB.
- Accept HTTPS URLs only and do not follow redirects.
- The original Indeed pre-signed URL must never appear in normal API responses, logs, or persisted public error messages.
- CI must not contact Indeed or AWS.
- Preserve existing candidate-import message compatibility.

---

### Task 1: Add durable Indeed resume state and migration 006

**Files:**
- Modify: `app/models.py`
- Modify: `app/domains/indeed/repository.py`
- Create: `app/migrations/versions/006_indeed_resume_ingestion.py`
- Modify: `app/tests/test_postgres_migrations.py`
- Create: `app/tests/test_indeed_resume_ingestion.py`

**Interfaces:**
- Produces ORM `IndeedResumeIngestion`.
- Produces repository helpers `get_or_create_resume_ingestion`, `get_resume_ingestion`, `list_undispatched_resume_ingestions`, `claim_resume_ingestion`, `heartbeat_resume_ingestion`, `release_resume_ingestion`.

- [ ] Add failing tests asserting one resume row per candidate link, default `PENDING`, durable stage/error fields, and owner scoping.
- [ ] Verify RED against the branch before production changes.
- [ ] Add the ORM model and relationship from `IndeedCandidateLink`.
- [ ] Add Alembic revision `006` after `005` with table, unique FK and owner/status indexes.
- [ ] Extend the PostgreSQL migration smoke to expect revision `006` and the new table/columns.
- [ ] Add repository create/get/claim/heartbeat/release/undispatched helpers using stale-lease semantics compatible with the existing worker lease timeout.
- [ ] Run targeted model/repository tests until GREEN.

### Task 2: Generalize the existing SQS envelope without breaking import batches

**Files:**
- Modify: `app/infrastructure/imports/queue.py`
- Modify: `app/workers/candidate_imports.py`
- Create: `app/tests/test_indeed_resume_queue.py`

**Interfaces:**
- Preserve `send_import_batch(batch_id)`.
- Add `send_indeed_resume_ingestion(resume_ingestion_id)`.
- Add `ReceivedWorkMessage(kind, identifier, receipt_handle, receive_count)`.
- Add `receive_work_messages()` accepting legacy batch payloads and new typed payloads.
- Existing `receive_import_messages()` may delegate/filter for backward compatibility.

- [ ] Write failing tests proving legacy `{schema_version,batch_id}` messages still deserialize as candidate-import work.
- [ ] Add failing tests for `kind=indeed_resume`, invalid kinds, missing identifiers, and send payload shape.
- [ ] Verify RED.
- [ ] Implement typed envelope and compatibility adapter.
- [ ] Add worker routing so candidate-import work reaches existing `process_batch`; Indeed work reaches a placeholder injectable `process_indeed_resume` boundary.
- [ ] Preserve SQS ACK/redrive behavior: delete only successful work; failures remain unacknowledged.
- [ ] Run queue/worker regression tests until GREEN.

### Task 3: Implement secure Indeed PDF download and canonical storage

**Files:**
- Create: `app/domains/indeed/resumes.py`
- Modify: `app/infrastructure/imports/storage.py`
- Test: `app/tests/test_indeed_resume_ingestion.py`

**Interfaces:**
- Produce dataclass `DownloadedResume(filename: str, data: bytes, sha256: str)`.
- Produce `download_resume(url, filename, http_client=None, max_bytes=20*1024*1024)`.
- Produce `create_canonical_candidate_download(candidate_id, expires_in=300)` from storage adapter.

- [ ] Add failing tests for non-HTTPS rejection, redirect rejection, Content-Length overflow, streamed overflow, empty body, non-PDF magic, filename normalization, and SHA-256.
- [ ] Verify RED.
- [ ] Implement streaming `httpx` download with bounded timeout, no redirects, no auth propagation and sanitized exceptions.
- [ ] Reuse `write_canonical_candidate_document` for persistence.
- [ ] Add storage helper that discovers the canonical PDF/DOCX and returns a five-minute S3 pre-signed GET URL without persisting it.
- [ ] Add tests for canonical write idempotency and pre-signed download generation.
- [ ] Run targeted tests until GREEN.

### Task 4: Make Bedrock ingestion reusable for one Indeed resume

**Files:**
- Modify: `app/infrastructure/imports/ingestion.py`
- Modify: `app/tests/test_candidate_import_ingestion_worker.py`
- Modify: `app/tests/test_indeed_resume_ingestion.py`

**Interfaces:**
- Add `start_ingestion(*, operation_key: str, description: str) -> tuple[str, str]`.
- Preserve `start_batch_ingestion(batch_id)` by delegating to the generic helper.
- Add `start_indeed_resume_ingestion(resume_ingestion_id, sha256)`.

- [ ] Add a failing test for deterministic Indeed operation token and unchanged candidate-import token semantics.
- [ ] Verify RED.
- [ ] Extract generic ingestion start helper using the existing KB/data-source configuration.
- [ ] Delegate old `start_batch_ingestion` to generic helper without changing its externally observed call values.
- [ ] Add Indeed helper keyed by ingestion id + SHA.
- [ ] Run existing import ingestion tests plus Indeed tests until GREEN.

### Task 5: Implement resumable Indeed resume worker pipeline

**Files:**
- Create: `app/workers/indeed_resumes.py`
- Modify: `app/workers/candidate_imports.py`
- Modify: `app/domains/indeed/repository.py`
- Modify: `app/tests/test_indeed_resume_ingestion.py`

**Interfaces:**
- Produce `process_resume_ingestion(resume_ingestion_id, receipt_handle=None)`.
- Produce `dispatch_undispatched_resume_ingestions(db) -> int`.
- Candidate-import worker invokes both dispatch repair loops and routes Indeed messages.

- [ ] Add failing tests for claim/duplicate claim, repair dispatch, missing link/URL, and stage resume from `STORED`, `INGESTING`, `EVALUATING`, and `RANKING`.
- [ ] Verify RED.
- [ ] `PENDING/DOWNLOADING`: securely download, SHA, write canonical S3, persist `STORED`.
- [ ] `STORED/INGESTING`: start/resume Bedrock ingestion, poll to COMPLETE, checkpoint `EVALUATING`; persist public-safe fail/timeout states.
- [ ] `EVALUATING`: call `evaluate_candidate_for_owner` with the same transient retry markers/delays used by candidate imports; require terminal evaluation; checkpoint `RANKING`.
- [ ] Force fresh evaluation when the stored resume SHA differs from the previously completed resume SHA; otherwise reuse a valid completed evaluation.
- [ ] `RANKING`: call `materialize_ranking_from_evaluations(..., scope="assigned")`; checkpoint `COMPLETED`.
- [ ] On unexpected transient errors leave the SQS message unacknowledged; on receive-count exhaustion mark `FAILED/RETRY_EXHAUSTED`.
- [ ] Add heartbeat/release behavior around active work.
- [ ] Run targeted worker tests until GREEN.

### Task 6: Wire Retrieve Candidates to durable resume processing

**Files:**
- Modify: `app/domains/indeed/candidates.py`
- Modify: `app/domains/indeed/service.py`
- Modify: `app/tests/test_indeed_candidate_sync.py`
- Modify: `app/tests/test_indeed_resume_ingestion.py`

**Interfaces:**
- A newly created `IndeedCandidateLink` with a resume URL produces exactly one `IndeedResumeIngestion`.
- Dispatch happens only after the DB state is durable.
- Repeated asset id returns existing task and never duplicates work.

- [ ] Add failing candidate-sync tests for task creation, no-resume case, idempotent repeated asset, queue dispatch success, and queue dispatch failure with repairable `queue_dispatched_at=None`.
- [ ] Verify RED.
- [ ] Create the durable resume task in the same transaction as the candidate/link.
- [ ] Commit before queue dispatch.
- [ ] Dispatch task and checkpoint `queue_dispatched_at`; on queue failure leave it null and do not roll back candidate ingestion.
- [ ] Ensure provider acknowledgment semantics remain unchanged.
- [ ] Run candidate-sync and resume tests until GREEN.

### Task 7: Expose canonical resume state/download without leaking Indeed URL

**Files:**
- Modify: `app/domains/indeed/service.py`
- Modify: `app/domains/indeed/router.py`
- Modify: `app/domains/indeed/schemas.py`
- Modify: `app/domains/candidates/router.py` or add a focused provider-neutral resume route alongside existing candidate routes
- Create/Modify: `app/tests/test_indeed_resume_routes.py`

**Interfaces:**
- Existing Indeed candidate detail response adds `resume.status`, `resume.available`, `resume.sha256`, `resume.last_error_code`, `resume.name`.
- Add `GET /api/jobs/{job_id}/candidates/{candidate_id}/resume` -> `{url, expires_in: 300}`.

- [ ] Add failing HTTP tests for owner isolation, unavailable CV 404/409 contract, completed CV URL success, and provider URL absence.
- [ ] Verify RED.
- [ ] Extend service presenter data without returning `IndeedCandidateLink.resume_url`.
- [ ] Implement provider-neutral canonical resume endpoint using S3 pre-sign helper.
- [ ] Ensure URL is generated per request and never stored.
- [ ] Run route tests until GREEN.

### Task 8: Update CandidateDetail UI

**Files:**
- Modify: `frontend-react/src/pages/CandidateDetail.jsx`
- Modify relevant CSS only if required
- Modify: `frontend-react/src/__tests__/CandidateDetailIndeed.test.jsx`

**Interfaces:**
- Reads resume status from existing Indeed candidate detail endpoint.
- Requests `/api/jobs/{job_id}/candidates/{candidate_id}/resume` only when user clicks `Ver CV`.

- [ ] Add failing UI tests for processing, failed, completed/available, and `Ver CV` click behavior.
- [ ] Verify RED.
- [ ] Show concise resume state with no provider URL in DOM.
- [ ] Add `Ver CV` button only for available canonical CV; fetch short-lived URL and open it.
- [ ] Run frontend lint/tests/build until GREEN.

### Task 9: Full verification and PR

**Files:**
- Review all branch changes.
- Update `app/tests/test_postgres_migrations.py` expectations if not already done in Task 1.

- [ ] Run full GitHub Actions on the final branch head.
- [ ] Require backend syntax/full pytest/contract tests green.
- [ ] Require frontend lint/tests/build green.
- [ ] Require PostgreSQL 16 Alembic smoke through revision `006` green.
- [ ] Review diff and remove unrelated formatting/refactors.
- [ ] Confirm no committed/provider resume URL or secret appears in logs/docs/tests except clearly fake `.invalid` fixtures.
- [ ] Open PR against `main` with live Indeed/AWS E2E explicitly listed as remaining work.
