# Candidate Ingestion Core — Design

Date: 2026-09-16
Status: Proposed for implementation
Branch: `architecture/candidate-ingestion-core`

## 1. Goal

Create a provider-neutral candidate ingestion subsystem that becomes the single entry point for candidate documents regardless of source. Email ingestion is the first production adapter. Existing manual bulk upload and Indeed flows must progressively converge on the same durable pipeline without breaking their current public contracts.

The target flow is:

```text
Source Adapter
  -> Candidate Ingestion Core
  -> durable event/document persistence
  -> S3
  -> shared SQS
  -> ingestion worker
  -> identity resolution
  -> candidate/job assignment
  -> Bedrock ingestion
  -> evaluation
  -> ranking
```

The core must not depend on Gmail, Indeed, or any single provider.

## 2. Current repository state

The repository already contains two strong but source-specific ingestion paths:

1. `app/domains/candidate_imports`
   - Bulk upload batches scoped to a known job.
   - Presigned S3 uploads.
   - PDF/DOCX/ZIP validation.
   - Candidate identity resolution.
   - Candidate/job assignment.
   - Durable SQS processing and Bedrock/ranking pipeline.

2. Indeed resume ingestion on top of PR #21
   - `IndeedResumeIngestion` durable state.
   - Download from provider URL.
   - Canonical S3 storage.
   - Bedrock ingestion.
   - Evaluation and ranking.
   - Shared SQS dispatcher.

These flows should be reused, not rewritten wholesale.

## 3. Approaches considered

### A. Generalize `ImportBatch`

Convert the existing bulk-import model into the universal ingestion model.

Rejected because `ImportBatch` assumes a known `job_id`, upload-manifest semantics, aggregate counters, and bulk processing. Email ingestion may arrive before a job is resolved and is event-oriented rather than batch-oriented.

### B. Keep one pipeline per provider

Add `indeed_email`, Gmail worker, and future provider-specific workers independently.

Rejected because it duplicates persistence, retry, identity, storage, evaluation, and ranking behavior. It also makes a future Indeed Apply API migration unnecessarily expensive.

### C. Introduce a provider-neutral ingestion event layer

Recommended. Add a small durable core that owns source identity, provider metadata, attached documents, state, idempotency, and dispatch. Existing source adapters translate their input into this model.

This minimizes provider coupling while preserving current working code.

## 4. Domain model

### 4.1 CandidateIngestionEvent

A single externally received candidate-ingestion event.

Fields:

- `id`: UUID primary key.
- `owner_sub`: tenant owner.
- `source`: normalized channel, initially `EMAIL`, `UPLOAD`, `PROVIDER_API`.
- `provider`: provider identifier, initially `INDEED`, `GENERIC_EMAIL`, `MANUAL`.
- `external_id`: provider/source idempotency key, for example Gmail message id or Indeed application id.
- `job_id`: nullable FK to jobs. It may be unresolved at receipt time.
- `candidate_id`: nullable FK to candidates. Populated after identity resolution.
- `status`: durable state.
- `raw_metadata`: JSON with normalized source metadata only; no large raw document bytes.
- `raw_s3_key`: optional S3 key for raw source payload when retention is required.
- `queue_dispatched_at`: nullable timestamp.
- `processing_token`: lease ownership token.
- `heartbeat_at`: lease heartbeat.
- `attempt_count`: retry counter.
- `last_error_code` / `last_error_message`: sanitized processing errors.
- `created_at`, `updated_at`, `completed_at`.

Idempotency constraint:

```text
UNIQUE(owner_sub, source, provider, external_id)
```

`external_id` is mandatory for machine-generated adapters. Manual upload continues to use its existing batch semantics initially.

### 4.2 CandidateIngestionDocument

One document attached to an ingestion event.

Fields:

- `id`: UUID primary key.
- `ingestion_event_id`: FK to ingestion event.
- `filename`: sanitized source filename.
- `content_type`.
- `size_bytes`.
- `source_s3_key`: immutable staging/raw document key.
- `document_sha256`: nullable until content is read.
- `canonical_s3_key`: nullable until candidate identity is resolved.
- `status`.
- `error_code` / `error_message`.
- timestamps.

Indexes support event/status lookup and SHA-based diagnostics.

Document identity is not globally unique because the same CV can legitimately be submitted to more than one job. Strong candidate identity continues to use the existing owner-scoped `CandidateIdentity` model.

## 5. State machine

Event states:

```text
RECEIVED
  -> STORED
  -> QUEUED
  -> PROCESSING
  -> IDENTIFIED
  -> INGESTING
  -> EVALUATING
  -> RANKING
  -> COMPLETED
```

Terminal/special states:

- `NEEDS_REVIEW`: source was valid but automatic job/candidate resolution cannot safely continue.
- `FAILED`: non-recoverable failure.
- `DUPLICATE`: optional presentation outcome when an adapter explicitly reports an already-ingested external event. The canonical DB row remains the original event.

State transitions must never move a terminal event back into processing without an explicit retry operation.

## 6. Core boundaries

New package:

```text
app/domains/candidate_ingestion/
  __init__.py
  models.py
  repository.py
  rules.py
  service.py
  presenter.py
  exceptions.py
```

Responsibilities:

### `service.py`

- Accept normalized ingestion requests.
- Enforce owner/source/provider idempotency.
- Persist event and document descriptors.
- Resolve a supplied job only when tenant ownership is verified.
- Queue durable work only after DB commit.
- Repair undispatched work.

### `rules.py`

- Source/provider normalization.
- State-transition validation.
- Safe filename and MIME rules shared by adapters.
- Metadata size limits.

### `repository.py`

- Owner-scoped event/document persistence.
- Lease claim/release.
- Undispatched-event lookup.
- Idempotent external-event lookup.

The core must not import Gmail or Indeed modules.

## 7. Queue contract

Extend the existing shared SQS queue with:

```text
kind = "candidate_ingestion"
ingestion_event_id = <uuid>
schema_version = 1
```

Historical messages remain valid:

- candidate import messages without `kind` still map to `candidate_import`.
- `indeed_resume` remains supported during migration.

The shared dispatcher gains a `candidate_ingestion` route. We do not remove current worker kinds in the first migration.

## 8. Worker design

Add:

```text
app/workers/candidate_ingestion.py
```

The worker owns provider-neutral stages after an adapter has durably stored the incoming document.

Initial worker responsibilities:

1. Load and claim event with lease.
2. Validate job context if already supplied.
3. Parse document using existing document parsing infrastructure.
4. Reuse existing `candidate_imports.service.resolve_or_create_candidate` identity semantics, extracted behind a provider-neutral helper where necessary.
5. Assign candidate to job when a job is resolved.
6. Write canonical candidate document.
7. Trigger Bedrock ingestion using existing infrastructure.
8. Evaluate candidate for the resolved job.
9. Materialize ranking.
10. Mark event complete.

If no job can be resolved safely, mark `NEEDS_REVIEW` and stop before AI evaluation.

## 9. Email adapter

New adapter package:

```text
app/integrations/email_ingestion/
  __init__.py
  schemas.py
  parser.py
  service.py
  providers/
    __init__.py
    indeed.py
    generic.py
```

The email adapter is intentionally transport-agnostic. It accepts a normalized email envelope from a mailbox client and produces a `CandidateIngestionRequest`.

Normalized input contains:

- mailbox message id.
- sender.
- recipients.
- subject.
- received timestamp.
- text metadata needed for provider parsing.
- attachment descriptors.

Provider parser selection:

```text
email envelope
  -> detect provider
  -> provider parser
  -> normalized ingestion request
  -> Candidate Ingestion Core
```

For Indeed email, the provider parser extracts candidate/job hints conservatively. Ambiguous job mapping results in `NEEDS_REVIEW`, not a guessed assignment.

## 10. Gmail/Workspace transport

Gmail is not part of the domain core. A later transport adapter will:

- authenticate using Google Workspace OAuth/service authorization appropriate to the mailbox.
- read only a dedicated ingestion mailbox or narrowly filtered messages.
- persist Gmail `message.id` as `external_id`.
- download accepted PDF/DOCX attachments.
- write source documents to S3 before creating/queuing an event.
- maintain a durable Gmail history cursor so polling is incremental.

Suggested mailbox:

```text
talent-ingestion@asiaticorp.com
```

The mailbox is machine-oriented; recruiters work in Asiati Talent.

## 11. Security and validation

Initial accepted documents:

- PDF.
- DOCX.

ZIP remains limited to the existing manual bulk-import flow until explicitly added to email ingestion.

Controls:

- sender/provider allowlist for automatic processing.
- MIME and extension validation.
- file-size limit using current 15 MiB document limit unless provider constraints require less.
- filename sanitization.
- SHA-256 on document bytes.
- no HTML/script execution.
- sanitized error messages.
- tenant ownership checks for every job/candidate relation.
- source URLs and secrets must never be persisted in public API responses.

Unknown/untrusted email becomes `NEEDS_REVIEW` or is rejected before candidate creation.

## 12. Job resolution

Email ingestion may not have a canonical job id. Resolution order:

1. Exact provider job mapping when available.
2. Exact owner-scoped public slug/external reference when present in normalized metadata.
3. Conservative title + location match only when exactly one active owner-scoped job matches.
4. Otherwise `NEEDS_REVIEW`.

AI/LLM matching must not silently choose a job in V1.

## 13. Candidate identity

Reuse the existing strong owner-scoped identity strategy:

- document SHA-256.
- normalized email.
- normalized phone.
- guarded legacy-email fallback.

Conflicting strong identities result in `NEEDS_REVIEW`/identity conflict instead of automatic merge.

The provider-specific external event id prevents duplicate source processing; candidate identity prevents duplicate people.

## 14. Existing-flow migration strategy

Implementation is incremental.

### Phase 1 — Core + email

- Add neutral event/document tables and queue kind.
- Add neutral worker.
- Add email normalization/provider parser.
- Do not remove `ImportBatch` or `IndeedResumeIngestion`.

### Phase 2 — Indeed convergence

- Adapt Indeed candidate/resume receipt to create a neutral ingestion event.
- Keep existing Indeed link tables for provider identifiers/disposition sync.
- Stop creating new provider-specific resume-processing rows once parity is proven.
- Remove `IndeedResumeIngestion` only in a later migration after existing rows are drained/migrated.

### Phase 3 — Manual upload convergence

- Keep bulk batch orchestration for upload UX/progress.
- Individual expanded documents may hand off to the neutral core.
- Preserve existing public batch endpoints and progress contracts.

This avoids a flag-day rewrite.

## 15. API/UI scope for V1

V1 backend should expose owner-scoped ingestion visibility, not a full new UI redesign.

Suggested endpoints:

```text
GET /candidate-ingestions
GET /candidate-ingestions/{id}
POST /candidate-ingestions/{id}/retry
POST /candidate-ingestions/{id}/resolve-job
```

Email transport itself should run server-side and not expose Gmail credentials to the browser.

A later UI can render an ingestion inbox with source, provider, candidate, job, status, and error/review state.

## 16. Testing strategy

TDD is required.

### Domain tests

- external-event idempotency.
- tenant isolation.
- valid/invalid state transitions.
- nullable job on receipt.
- job ownership enforcement.
- document metadata validation.
- identity conflicts.

### Queue/worker tests

- `candidate_ingestion` serialization/deserialization.
- dispatcher routing.
- durable commit-before-dispatch semantics.
- repair of undispatched events.
- lease exclusivity and stale lease recovery.
- retry/DLQ behavior.
- checkpoint resume after partial processing.

### Email tests

- provider detection.
- Indeed subject/body fixture parsing.
- PDF/DOCX attachment acceptance.
- duplicate Gmail message id.
- ambiguous job -> `NEEDS_REVIEW`.
- untrusted sender does not create a candidate.

### Database tests

- Alembic `007` from current branch head `006`.
- PostgreSQL migration smoke.
- unique constraints/indexes.

### Regression

Existing candidate-import, Indeed, evaluation, ranking, frontend, and contract suites must continue passing.

## 17. Migration numbering

This branch is intentionally based on the current Indeed resume-ingestion branch where migration `006` exists. The Candidate Ingestion Core migration will therefore be `007` and revise `006`.

This prevents a future Alembic head conflict when the Indeed resume work lands.

## 18. Non-goals for the first implementation

- Browser automation against Indeed.
- Replacing the Indeed Partner/API work.
- Gmail OAuth UI.
- AI-based automatic job guessing.
- Replacing bulk import endpoints.
- Deleting provider-specific Indeed persistence immediately.
- A complete new ingestion dashboard before the backend core is stable.

## 19. Success criteria

The first production-ready increment is complete when:

1. A normalized email event with a PDF/DOCX attachment can be accepted idempotently.
2. The event and document are durably persisted before dispatch.
3. The shared worker processes the event through the existing identity/S3/Bedrock/evaluation/ranking stack when a job is resolved.
4. Ambiguous job mapping becomes `NEEDS_REVIEW` without creating an incorrect assignment.
5. Duplicate source messages do not create duplicate ingestion events or candidates.
6. Existing manual import and Indeed flows remain operational.
7. SQLite/unit/contract tests and PostgreSQL/Alembic smoke are green.

## 20. Immediate implementation order

1. Persistence models + Alembic `007`.
2. Repository/rules/service TDD.
3. Queue kind + dispatcher route.
4. Provider-neutral worker using existing pipeline primitives.
5. Email adapter + Indeed email parser fixtures.
6. Owner-scoped ingestion API.
7. Gmail/Workspace transport as the first mailbox connector.
8. Production hardening and observability.
