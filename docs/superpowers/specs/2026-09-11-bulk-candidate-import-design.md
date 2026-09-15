# Bulk Candidate Import V1 — Design Specification

**Date:** 2026-09-11  
**Branch:** `feature/bulk-candidate-import`  
**Base:** `main` at `0cbf7fd74893174e96bf9d765576c6821ac82650`  
**Tracking issue:** #8  
**Status:** design approved in chat; implementation requires a separate implementation-plan approval

## 1. Purpose

Build a production-grade bulk candidate import flow for AI Recruiter that lets a recruiter select a job, upload up to 500 CVs, leave the browser, and later return to a persisted, automatically generated ranking.

The V1 flow is:

`upload -> validate -> deduplicate -> index -> evaluate -> rank -> complete`

The workflow must be durable across API/worker restarts, tenant-safe, idempotent, and transparent about real processing state. UI motion must reflect backend state rather than simulated progress.

## 2. Explicit scope

### Included

- Up to **500 candidate documents per import batch**.
- Input formats: **PDF, DOCX, ZIP**.
- A batch is always associated with one selected job before processing starts.
- Direct browser-to-S3 upload through presigned S3 POSTs.
- Durable asynchronous execution through **Amazon SQS Standard**.
- An SQS **dead-letter queue (DLQ)**.
- A separate Docker worker running the same backend image as the API.
- Automatic conservative deduplication.
- Automatic candidate creation/reuse and job assignment.
- One logical Bedrock Knowledge Base ingestion job per batch when canonical candidate documents changed.
- Automatic candidate evaluation against the selected job.
- Automatic ranking update after evaluation.
- Persisted batch/item states in PostgreSQL.
- REST polling for real progress.
- Animated frontend state transitions, progress indicators, skeletons, and progressive results.
- `prefers-reduced-motion` support.
- Recovery after browser refresh and worker/API restart.

### Explicitly excluded

- No CV/source-origin field.
- No Computrabajo/LinkedIn/referral/manual source metadata.
- No Browser Use integration or scraping.
- No WebSocket or SSE transport in V1.
- No fuzzy/name-only automatic candidate merge.
- No Kubernetes, Celery, or Redis.
- No fake aggregate progress percentage.

## 3. Current-state constraints

The current `/api/candidates/bulk` endpoint processes files synchronously inside the FastAPI request. It creates candidates one by one and calls the current document indexing function for every candidate. That indexing function uploads the document and starts a Bedrock Knowledge Base ingestion job for each candidate.

The current React Candidates page already accepts multiple PDF files and sends batches of 25 to `/api/candidates/bulk`, then separately assigns returned candidate IDs to a job. This UI should evolve rather than add a second unrelated candidate-management screen.

Current evaluation persistence is already idempotent at the `(candidate_id, job_id)` application level: creating an evaluation updates the existing candidate/job evaluation if present. Current ranking orchestration can skip already-complete evaluations in incremental mode. The importer should reuse those domain services rather than call its own HTTP API.

The legacy `/api/candidates/bulk` API remains intact during V1 for compatibility. The new UI will move to the new import-batch API. Removing the legacy endpoint is a separate future change.

## 4. Architecture

```text
React Candidate Import UI
        |
        | 1. create batch + upload manifest
        v
FastAPI candidate-import API ---------------------- PostgreSQL
        |                                               |
        | 2. presigned S3 POSTs                         | persisted state
        v                                               |
Browser ---------------------> import staging S3 bucket |
        |                                               |
        | 3. confirm uploads                            |
        v                                               |
FastAPI ---------------------> SQS Standard             |
                                  |                     |
                                  v                     |
                         candidate-import worker <-------+
                                  |
              +-------------------+-------------------+
              |                   |                   |
              v                   v                   v
       staging/canonical S3   Bedrock KB         PostgreSQL
              |                   |                   |
              +-------------------+-------------------+
                                  |
                           Evaluations service
                                  |
                           Ranking service
                                  |
                                  v
                       persisted terminal result
                                  ^
                                  |
                         REST polling every ~2s
                                  |
                                React
```

### Why this architecture

- CV bytes do not traverse FastAPI, so a 500-document import does not hold large HTTP requests or API memory.
- SQS gives at-least-once durable delivery and survives API/worker restarts.
- PostgreSQL is the source of truth for progress and resumability.
- A dedicated worker avoids coupling long-running Bedrock work to API request lifetime.
- A dedicated staging bucket prevents raw ZIPs and temporary files from accidentally entering the Bedrock data source.
- The existing canonical candidate-document bucket/prefix remains the only source used for Knowledge Base ingestion.

## 5. Component boundaries

### Backend domain

Create `app/domains/candidate_imports/` with the same modular-monolith pattern used by Candidates, Evaluations, Jobs, and Ranking:

```text
app/domains/candidate_imports/
  __init__.py
  exceptions.py
  presenter.py
  repository.py
  router.py
  schemas.py
  service.py
  rules.py
```

Responsibilities:

- **router**: HTTP-only concerns, dependencies, status-code/error mapping.
- **service**: owner-scoped use cases and orchestration exposed to HTTP and the worker.
- **repository**: ImportBatch/ImportItem/CandidateIdentity persistence only.
- **rules**: state transitions, normalizers, identity resolution policy, size/count rules.
- **presenter**: stable public response shapes.
- **schemas**: request/response validation.
- **exceptions**: domain/application errors.

The candidate-import router must not import `app.crud`, SQLAlchemy models directly, or AWS clients.

### Infrastructure

Add focused infrastructure modules, not AWS calls inside domain routers:

```text
app/infrastructure/imports/
  storage.py       # presigning, staging reads/deletes, canonical document writes
  queue.py         # SQS send/receive/delete/change-visibility
  documents.py     # PDF/DOCX validation + text/contact extraction + safe ZIP expansion
  ingestion.py     # one idempotent Bedrock KB ingestion start/poll operation
```

### Worker

```text
app/workers/candidate_imports.py
```

The worker dispatches any durable queued batches that were not successfully sent to SQS, consumes SQS messages, claims a batch, runs/resumes its state machine, checkpoints progress, and acknowledges the SQS message only after a terminal state or intentional retry behavior.

### Frontend

Do not make the already-large `Candidates.jsx` own the entire async state machine. Add a focused feature boundary:

```text
frontend-react/src/features/candidate-import/
  CandidateImportModal.jsx
  ImportProgress.jsx
  ImportSummary.jsx
  useCandidateImport.js
  api.js
```

`Candidates.jsx` opens the feature and refreshes candidate data when an import reaches a terminal state. Existing ASIATI visual variables remain the design source.

## 6. Persistence model

A new Alembic migration follows the existing `002` migration as `003`.

### 6.1 `ImportBatch`

Required fields:

- `id` UUID primary key
- `job_id` FK -> jobs with `ON DELETE CASCADE`, non-null
- `owner_sub` text, non-null
- `status` text, non-null
- `current_stage` text, non-null
- `upload_total` integer, default 0
- `uploaded_items` integer, default 0
- `total_items` integer, default 0
- `processed_items` integer, default 0
- `successful_items` integer, default 0
- `reused_items` integer, default 0
- `failed_items` integer, default 0
- `evaluated_items` integer, default 0
- `evaluation_failed_items` integer, default 0
- `ranking_ready` boolean, default false
- `ranking_version` integer nullable
- `bedrock_ingestion_job_id` text nullable
- `attempt_count` integer, default 0
- `queue_dispatched_at` timestamp nullable
- `processing_token` text nullable
- `heartbeat_at` timestamp nullable
- `last_error_code` text nullable
- `last_error_message` text nullable; public-safe text only
- `created_at`, `started_at`, `completed_at`, `updated_at`

`ON DELETE CASCADE` preserves the existing job-deletion behavior: import history must not prevent deleting a job. A worker that receives a message for a batch deleted by job cascade acknowledges/discards that message without recreating state.

Indexes support owner/job/recent-batch queries and worker state queries.

Counter semantics are fixed:

- `upload_total`: user-selected top-level uploads (documents + ZIP containers)
- `uploaded_items`: successfully uploaded top-level objects
- `total_items`: discovered processable `DOCUMENT` items after ZIP expansion
- `processed_items`: document items that reached a preparation terminal state
- `successful_items`: prepared/assigned document items, including reused candidates
- `reused_items`: subset of `successful_items` whose candidate already existed
- `failed_items`: document items that failed preparation/deduplication
- `evaluated_items`: successful items whose evaluation attempt reached a terminal result
- `evaluation_failed_items`: subset of `evaluated_items` whose evaluation is `FAILED`

### 6.2 `ImportItem`

One row represents either a direct candidate document or an archive container. ZIP expansion creates child document rows.

Required fields:

- `id` UUID primary key
- `batch_id` FK -> import_batches with cascade delete
- `parent_item_id` self-FK nullable; used for documents expanded from a ZIP
- `kind`: `DOCUMENT` or `ARCHIVE`
- `original_filename`
- `staging_s3_key`
- `content_type`
- `size_bytes`
- `document_sha256` nullable until validated
- `candidate_id` FK -> candidates with `ON DELETE SET NULL`, nullable
- `status`
- `current_stage`
- `outcome`: nullable, `CREATED` or `REUSED` for successful document items
- `error_code` nullable
- `error_message` nullable; public-safe text only
- `created_at`, `updated_at`, `completed_at`

Deleting a candidate must not break import-history rows; the nullable candidate FK is cleared instead.

Batch counters count only `DOCUMENT` rows after archive expansion. Archive rows are containers and do not represent candidates.

### 6.3 `CandidateIdentity`

Use a separate identity table so deduplication is indexed and tenant-scoped without overloading Candidate metadata.

Required fields:

- `id` UUID primary key
- `owner_sub` text, non-null
- `candidate_id` FK -> candidates with cascade delete
- `kind`: `DOCUMENT_SHA256`, `EMAIL`, or `PHONE`
- `value` normalized text, non-null
- `created_at`

Constraint:

`UNIQUE(owner_sub, kind, value)`

This prevents two candidates owned by the same tenant from claiming the same strong identity. Identical values in different tenants are independent.

Identity insertion is race-safe: on a unique-constraint collision, re-read the identity. If it now points to the same candidate, treat the operation as idempotent; if it points to a different candidate, stop that item as `IDENTITY_CONFLICT` rather than merging.

There is **no source/origin column** in any import or candidate identity table.

### 6.4 Existing-candidate identity bootstrap

The new identity table must work with candidates created before migration `003`.

Deliver an idempotent application backfill command that:

1. reads existing candidates owner-by-owner
2. seeds normalized email identities from non-empty existing `Candidate.email` values when unambiguous
3. hashes the existing canonical S3 candidate document when available and seeds `DOCUMENT_SHA256`
4. skips ambiguous legacy identity collisions instead of choosing a winner
5. emits counts/IDs in logs without raw CV text

The importer additionally treats an ambiguous legacy normalized email match as `IDENTITY_CONFLICT` until the legacy data is resolved. No migration invents phone values that are not already known.

## 7. Batch and item state machines

### Batch status

Non-terminal:

- `UPLOADING`
- `QUEUED`
- `PROCESSING`

Terminal:

- `COMPLETED`
- `COMPLETED_WITH_ERRORS`
- `FAILED`

### Batch stage

- `UPLOADING`
- `VALIDATING`
- `DEDUPLICATING`
- `INGESTING`
- `EVALUATING`
- `RANKING`
- `COMPLETED`

For `FAILED`, `current_stage` remains the stage that failed. `COMPLETED` and `COMPLETED_WITH_ERRORS` end with `current_stage=COMPLETED`.

### Item status

- `UPLOADING`
- `UPLOADED`
- `PROCESSING`
- `COMPLETED`
- `FAILED`

`current_stage`, `outcome`, and `error_code` provide finer-grained item information without creating an excessive status enum.

State-transition functions live in `rules.py` and are unit-tested. Terminal batches/items cannot silently move back to active states.

## 8. Public API

All endpoints require Cognito authentication and scope every read/write by `owner_sub`.

### 8.1 Create batch

`POST /api/import-batches`

Request:

```json
{
  "job_id": "uuid",
  "uploads": [
    {
      "filename": "candidate.pdf",
      "size_bytes": 123456,
      "content_type": "application/pdf"
    }
  ]
}
```

The service verifies the job belongs to the owner before creating anything.

Response includes:

- `batch_id`
- batch status/stage
- one upload descriptor per selected file
- S3 presigned POST URL + signed fields
- expiration timestamp

Presigned upload credentials expire after one hour. Signed POST conditions enforce the expected object key and an appropriate content-length range; worker validation remains authoritative for file type/content.

### 8.2 Complete uploads / durable enqueue

`POST /api/import-batches/{batch_id}/complete`

Database commit and SQS delivery are not falsely treated as one atomic transaction.

Behavior:

1. owner-scope batch
2. verify every declared staging object exists and has an acceptable size
3. mark items uploaded
4. commit batch as `QUEUED` with `queue_dispatched_at=NULL`
5. attempt to send the SQS message
6. after a successful send, persist `queue_dispatched_at`

The operation is idempotent. Repeating it after the batch has already been queued or started returns current state; if the batch is queued but `queue_dispatched_at` is still null, it safely retries dispatch.

For crash/network gaps, the worker loop also scans `QUEUED` batches with `queue_dispatched_at=NULL` before/around long polling and dispatches them. If a send succeeds but the sender crashes before persisting `queue_dispatched_at`, a later retry may create a duplicate SQS message; the batch lease/state machine makes that duplicate harmless.

### 8.3 Batch progress

`GET /api/import-batches/{batch_id}`

Response contains real persisted counters, stage, status, terminal summary, and ranking readiness/version. It never returns internal AWS errors, raw CV text, S3 credentials, or queue metadata.

### 8.4 Batch items

`GET /api/import-batches/{batch_id}/items?page=1&page_size=100`

Returns owner-scoped document/archive rows for progressive UI display and failure diagnostics.

### 8.5 Recent job imports

`GET /api/import-batches?job_id={job_id}&limit=10`

Allows the frontend to recover an active/recent batch after refresh, logout/login, or navigation without relying solely on browser local storage.

## 9. Upload rules and staging security

### Direct documents

- Allowed: `.pdf`, `.docx`.
- Maximum: 15 MiB per candidate document, preserving the current UI limit.
- Extension alone is insufficient; worker validates file structure/signature.

### ZIP archives

- Allowed as an upload container only.
- Maximum compressed ZIP size: 500 MiB.
- Maximum expanded candidate-document count for the entire batch: 500.
- Maximum total expanded document bytes for the entire batch: 1 GiB.
- Only PDF and DOCX children are accepted.
- Nested ZIP/archive processing is rejected.
- Absolute paths, `..` traversal, symlinks, and unsafe entries are rejected.
- macOS metadata/hidden archive entries that are not candidate documents are ignored.

If safe expansion would exceed the 500-document or 1-GiB batch ceiling, the batch fails validation before creating candidates.

### Staging bucket

Use a dedicated import-staging S3 bucket in `us-east-2`, separate from the current Bedrock knowledge-source bucket. This guarantees raw ZIPs and temporary upload objects cannot be ingested by the Knowledge Base.

The staging bucket has:

- private access only
- Block Public Access enabled
- server-side encryption
- CORS restricted to the production frontend origin and explicitly configured development origins only
- a lifecycle rule that removes abandoned staging objects after 24 hours

Worker cleanup deletes terminal-batch staging objects eagerly; lifecycle is the fallback.

## 10. Conservative deduplication policy

Deduplication is owner-scoped. Candidate identity never crosses tenant boundaries.

### Strong automatic identifiers

1. SHA-256 of the candidate document
2. normalized candidate email
3. normalized candidate phone

Candidate name is **never** sufficient for an automatic merge.

### Contact extraction

PDF/DOCX text extraction uses deterministic local parsing, not an extra LLM call.

To reduce false matches from references or unrelated people, email/phone identity extraction is limited to the document's contact/header region. If multiple conflicting values of the same identity type are found in that region, that identity type is considered ambiguous and is not used for automatic deduplication.

For a new candidate, the display name is derived deterministically from a plausible document header when available, with the normalized filename stem as fallback. Display name is never an identity key. An unambiguous extracted email populates `Candidate.email` for a new candidate. Reusing a candidate does not overwrite a different non-empty existing email merely because a newly uploaded CV contains another address.

### Resolution algorithm

For each document:

1. calculate SHA-256
2. extract/normalize unambiguous email and phone when available
3. resolve all strong identities against `CandidateIdentity` for the current owner, with legacy-email fallback during transition
4. if no identity matches, create a new Candidate
5. if every matched identity resolves to the same Candidate, reuse it
6. if strong identities resolve to more than one existing Candidate, do **not** merge; fail only that item with `IDENTITY_CONFLICT`

### Existing-candidate document behavior

- Same candidate + same document hash: reuse candidate; do not rewrite/reingest the canonical CV.
- Candidate matched by email/phone + different document hash: reuse candidate and update the canonical CV with the new document.
- New strong identities that unambiguously belong to the resolved candidate are attached to that candidate.
- Within one batch, the first successfully processed new document for a candidate becomes the canonical update. Later different documents resolving to that same candidate are treated as reused duplicates and do not repeatedly overwrite the CV in the same batch.

Every successfully created/reused candidate is idempotently assigned to the selected job.

## 11. Canonical candidate storage and Bedrock ingestion

Staging objects are never queried by Bedrock.

Successful new/updated candidate documents are copied/written to the existing canonical candidate-document area used by the Knowledge Base, with their real extension and MIME type. Candidate metadata files preserve the canonical `candidate_id` filter required by retrieval.

If a canonical document changes extension, stale canonical variants for that candidate are removed so the Knowledge Base does not retain multiple active CV objects for the same candidate.

### One logical ingestion job per batch

After all documents are prepared:

- if at least one canonical candidate document changed, call `start_ingestion_job` for the batch
- use a deterministic Bedrock `clientToken` derived from the batch ID so retrying the start request cannot create a second logical ingestion job
- persist `bedrock_ingestion_job_id` immediately from the successful response
- persist a short batch-ID description for operations/debugging
- poll the real Bedrock ingestion job state
- only enter `EVALUATING` when ingestion completes successfully
- if every item was an unchanged reused candidate, skip ingestion and move directly to evaluation

Transport/API retries reuse the same client token. A Bedrock job that itself reaches `FAILED` is treated as a fatal ingestion-stage failure in V1 rather than starting a second ingestion job with a different token.

The UI must show Bedrock ingestion as an indeterminate active stage because Bedrock does not provide a trustworthy per-document percentage through the existing flow.

## 12. SQS and worker execution

### Queue

Provision in `us-east-2`:

- one SQS Standard queue
- one DLQ
- redrive after 5 receives
- long polling (20 seconds)

Message body contains only:

```json
{
  "schema_version": 1,
  "batch_id": "uuid"
}
```

No CV contents, candidate PII, job text, or credentials are placed on SQS.

### Worker deployment

Run a third production container on the current Lightsail host:

- `ai-recruiter-api` -> existing Uvicorn command
- `ai-recruiter-web` -> existing frontend container
- `ai-recruiter-worker` -> `python -m app.workers.candidate_imports`

The worker uses the same immutable backend image SHA, database, Roles Anywhere mounts, AWS region, and network as the API. It runs with `--restart unless-stopped` through a dedicated deploy script analogous to the API deployment script.

V1 runs **one worker process**. This intentionally serializes Knowledge Base ingestion jobs and avoids concurrent ingestion conflicts. Evaluation inside a batch may use bounded concurrency.

### Claim/lease and duplicate delivery

SQS Standard is at-least-once, so duplicate messages are expected behavior.

A worker must atomically claim a non-terminal batch using `processing_token` + `heartbeat_at`. It refreshes the heartbeat while processing. A second worker/message cannot actively process a batch with a fresh lease.

A stale lease can be reclaimed after a configured timeout. The worker then inspects persisted batch/item stages and resumes rather than restarting completed work.

The worker periodically extends the SQS message visibility timeout while the batch is active.

On an unhandled retryable error, the message is not acknowledged. On the fifth receive, the worker records a public-safe `FAILED` batch state before allowing the message to move to the DLQ.

If a message references a missing/cascade-deleted batch, the worker acknowledges it as obsolete.

## 13. Evaluation strategy

After successful ingestion, evaluate every successfully prepared candidate against the selected job automatically.

Use the existing Evaluations application service and a fresh SQLAlchemy session per concurrent evaluation task.

V1 default:

- `IMPORT_EVALUATION_CONCURRENCY=3`
- configurable by environment variable
- bounded exponential backoff for explicitly retryable throttling/transient provider failures

Progress is checkpointed after each completed evaluation attempt:

- `evaluated_items` increments for each finished candidate evaluation
- `evaluation_failed_items` increments for failed evaluations

A failed candidate evaluation does not abort the whole batch; the batch can finish as `COMPLETED_WITH_ERRORS`.

## 14. Ranking strategy

Do not call the public ranking endpoint from the worker.

Add a Ranking application-service entry point that materializes a new ranking version **from already persisted evaluations** without triggering another evaluation pass. It must:

- owner-scope the job
- use the existing job ranking lock
- include assigned candidates only for this import flow
- order completed/failed/pending candidates with existing ranking semantics
- persist ranking metadata/items
- return the generated ranking version

The existing `recalculate_ranking()` public behavior remains unchanged. This small service addition prevents duplicate Bedrock evaluation calls after the import worker has already evaluated all candidates.

If another ranking operation temporarily owns the job lock, the import worker treats that as retryable with bounded backoff instead of immediately failing the batch.

When ranking persistence succeeds, set `ranking_ready=true` and persist `ranking_version` on the batch.

## 15. Progress and animation semantics

The backend is the source of truth. Animation smooths transitions; it never invents work.

### Polling

While a batch is active:

- foreground tab: poll `GET /api/import-batches/{id}` approximately every 2 seconds
- background/hidden tab: back off to a slower cadence
- stop polling at `COMPLETED`, `COMPLETED_WITH_ERRORS`, or `FAILED`

Items may be refreshed separately/paginated for progressive file rows.

### Real progress only

Do not construct a fake cross-stage `0-100%` value.

Display stage-specific measurable progress:

- **UPLOADING:** actual bytes uploaded / declared bytes from browser upload progress events
- **VALIDATING / DEDUPLICATING:** processed document count / total discovered document count
- **INGESTING:** indeterminate animated indicator using real Bedrock job state
- **EVALUATING:** evaluated items / successful items
- **RANKING:** indeterminate animated indicator until ranking commit succeeds

### Motion

Use subtle ASIATI-compatible transitions:

- progress-bar interpolation between real values
- skeleton/processing indicators
- checkmark/error state transitions
- progressive appearance/update of file/candidate rows
- terminal completion summary and `Ver ranking` action

Under `prefers-reduced-motion: reduce`, remove nonessential transforms/transitions and preserve status changes without motion.

## 16. Terminal semantics

### `COMPLETED`

All processable documents prepared successfully, evaluations completed successfully, and ranking persisted.

### `COMPLETED_WITH_ERRORS`

At least one candidate/item/evaluation failed, but at least one candidate was successfully prepared and the final ranking was persisted for all available results.

Examples:

- one malformed CV among 100 valid CVs
- one `IDENTITY_CONFLICT`
- one evaluation returns `FAILED`

### `FAILED`

The batch cannot produce a usable ranking or a fatal pipeline stage failed.

Examples:

- unsafe/oversized archive invalidates the batch before candidate creation
- no candidate document can be prepared
- Bedrock ingestion fails/times out when changed documents require ingestion
- selected job no longer exists/is no longer visible
- retry ceiling is exhausted by a fatal worker failure

Technical errors remain in structured logs. API-visible `error_message` values are sanitized.

## 17. Idempotency and recovery

Every external stage is designed to be replay-safe:

- completing uploads twice does not create two logical batches
- DB/SQS dispatch gaps are recovered through `queue_dispatched_at` scanning
- SQS duplicate delivery does not create duplicate candidates because identity constraints + batch lease apply
- identity unique-constraint races are re-read and resolved conservatively
- candidate/job assignment is already idempotent
- candidate/job evaluation updates existing evaluation instead of creating duplicates
- Bedrock ingestion start uses a deterministic client token
- unchanged canonical CVs are not reuploaded/reingested
- completed item stages are skipped on resume
- ranking is materialized once at the terminal ranking stage for a claimed execution

A worker restart during any stage resumes from PostgreSQL checkpoints.

## 18. AWS permissions and infrastructure delivery

Infrastructure is provisioned explicitly rather than implicitly on every application startup.

Add a versioned infrastructure definition/provisioning path for:

- import staging S3 bucket + CORS + lifecycle
- SQS queue
- SQS DLQ + redrive policy
- runtime role permissions required by API/worker

Minimum runtime capabilities are limited to the specific import bucket/queue and existing canonical/Bedrock resources required by this application:

- API: presign staging writes, verify staging objects, send SQS messages
- worker: receive/delete/change-visibility SQS messages, staging object read/delete, canonical candidate-document write/delete, Bedrock ingestion start/read, existing Bedrock retrieval/evaluation operations

Do not broaden permissions to wildcard resources where resource-level scoping is supported.

The existing deploy workflow/script is the operational source of truth for the current Lightsail Docker deployment. Historical infrastructure documentation must not cause this feature to reintroduce an old ECS deployment path.

## 19. Deployment and migration changes

Add a worker deploy script and extend CI/CD so a successful main deploy verifies:

1. backend image built/pushed by immutable SHA as today
2. migration `003` is applied before code that requires the new tables becomes active
3. existing-candidate identity bootstrap is safe/idempotent and can be executed during controlled deployment
4. API container healthy
5. worker container uses the same SHA image
6. worker container is running with required Roles Anywhere mounts/env
7. frontend deployment remains healthy

Worker deployment must preserve/allow rollback of the previous worker image in the same spirit as API/frontend rollback.

Migration/backfill ordering must not leave the existing API unable to start. The schema migration creates structures first; the identity backfill is idempotent application work and must not be required for ORM import/startup correctness.

## 20. Testing strategy

Implementation follows strict RED -> GREEN TDD.

### Domain/unit tests

Cover:

- legal/illegal batch transitions
- counter semantics
- 500-document ceiling
- normalization of email/phone
- SHA-256 identity handling
- no name-only merging
- same-tenant deduplication
- cross-tenant isolation
- multi-identity same-candidate reuse
- multi-identity different-candidate `IDENTITY_CONFLICT`
- identity unique-race resolution
- first-document-wins behavior for multiple documents resolving to one candidate in a batch
- terminal counters/status calculation

### Document/archive tests

Cover:

- valid PDF
- valid DOCX
- valid ZIP with PDF/DOCX
- nested ZIP rejection
- path traversal rejection
- symlink rejection
- malformed archive
- unsupported files
- empty files
- per-file size limits
- expanded-byte/document-count limits

### Service/API tests

Cover:

- owner-scoped job requirement
- batch creation/presign contract
- upload completion verification
- queued state committed before external SQS dispatch
- dispatch recovery when `queue_dispatched_at` is null
- duplicate dispatch safety
- idempotent completion/enqueue
- owner cannot read/complete another tenant batch
- status and item pagination contracts
- public error sanitization

### Legacy identity bootstrap tests

Cover:

- normalized existing email identity creation
- canonical S3 hash identity creation
- idempotent rerun
- ambiguous legacy email skip/conflict behavior
- cross-tenant same email remains independent

### Queue/worker tests

Use mocked AWS clients and real service boundaries where practical. Cover:

- SQS message shape contains only batch ID/schema version
- duplicate delivery
- fresh lease blocks second worker
- stale lease recovery
- visibility extension
- missing/cascade-deleted batch acknowledgement
- stage resume after simulated crash
- fifth-attempt failure behavior
- deterministic Bedrock ingestion `clientToken`
- one logical Bedrock ingestion start per changed batch under retries
- no ingestion when all candidates are unchanged reuses

### Evaluation/ranking tests

Cover:

- evaluation progress accounting
- partial evaluation failures produce `COMPLETED_WITH_ERRORS`
- ranking materialization does not invoke evaluation/LLM again
- ranking lock retry behavior
- ranking version persisted onto ImportBatch

### Compatibility/deletion tests

Cover:

- deleting a job with import history still preserves the established Jobs delete contract
- import batch/items cascade with job deletion
- deleting a candidate sets historical `ImportItem.candidate_id` to null
- CandidateIdentity rows cascade with candidate deletion

### Frontend tests

Cover:

- manifest validation
- direct S3 upload progress
- polling lifecycle/backoff/terminal stop
- stage-specific progress (no fake aggregate percent)
- reload recovery via recent-batch endpoint
- terminal success/partial-error/failure summaries
- `prefers-reduced-motion`

### Regression/verification

Before merge:

- full backend SQLite suite
- contract suite
- PostgreSQL smoke suite
- frontend lint/tests/build
- architecture-boundary tests
- migration upgrade test from `002 -> 003`
- deploy-contract tests for worker additions

Existing Candidate, Evaluation, Job, Ranking, authentication, ASIATI branding, and legacy bulk-upload public contracts must stay green unless explicitly covered by this spec.

## 21. Observability and privacy

Structured logs include:

- `batch_id`
- item/candidate IDs where needed
- stage/status
- retry/attempt information
- provider operation outcome

Logs must not include:

- raw CV text
- uploaded file bytes
- presigned credentials
- Cognito tokens
- unnecessary extracted contact data

Batch APIs expose only sanitized errors suitable for recruiters.

## 22. Acceptance criteria

V1 is complete when all of the following are true:

1. A recruiter can select a job and submit PDF/DOCX/ZIP input that resolves to at most 500 CV documents.
2. Uploads go directly from browser to private staging S3 using expiring presigned POST credentials.
3. Closing/reloading the browser does not cancel processing or lose recoverable status.
4. DB-to-SQS dispatch gaps recover without losing a queued batch.
5. SQS + a separate worker execute the pipeline durably.
6. Duplicate candidates are automatically reused by owner-scoped hash/email/phone rules; names alone never merge.
7. Pre-existing candidates participate in deduplication through safe identity bootstrap/legacy fallback.
8. Identity conflicts do not merge people and do not abort unrelated items.
9. Candidate links to the selected job are idempotent.
10. Changed canonical CVs trigger one logical Bedrock KB ingestion job for the batch using an idempotent client token; unchanged-only batches trigger none.
11. Successful candidates are automatically evaluated against the selected job.
12. The final ranking is materialized without a second evaluation pass.
13. The UI displays real upload/document/evaluation counters and indeterminate states where the provider exposes no measurable percentage.
14. Animations respect reduced-motion preferences.
15. Partial item/evaluation failures produce a useful `COMPLETED_WITH_ERRORS` result and ranking when possible.
16. Worker/API restart and duplicate SQS delivery do not create duplicate candidates/evaluations or lose the batch.
17. Existing job/candidate deletion contracts continue to work with the new foreign keys.
18. No source/origin tracking and no Browser Use are introduced.
19. Full SQLite, PostgreSQL, contract, architecture, frontend, migration, and deployment verification is green before merge.
