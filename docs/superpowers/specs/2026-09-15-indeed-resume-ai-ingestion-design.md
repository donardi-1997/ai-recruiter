# Indeed Resume Ingestion + AI Evaluation Design

## Goal

Extend the Indeed candidate integration so a candidate retrieved from Indeed can move from a temporary Indeed resume URL into Asiati Talent's durable document, Bedrock evaluation, and ranking pipeline without introducing a second AWS queue or treating an Indeed resume as a manual upload.

## Scope

This phase includes:

- durable per-candidate Indeed resume-processing state;
- secure download of the Indeed pre-signed resume PDF;
- PDF validation, bounded download size, and SHA-256 calculation;
- canonical S3 persistence through the existing candidate-document storage adapter;
- Bedrock Knowledge Base ingestion;
- AI evaluation for the candidate/job pair;
- ranking materialization after successful evaluation;
- idempotent retries and durable failure state;
- same SQS queue and worker process already used by candidate imports, with a typed work-message envelope;
- candidate-detail API/UI state for resume processing and a canonical CV download link after the document is stored;
- tests using mocked HTTP/AWS/Bedrock transports; CI never downloads from Indeed or invokes live AWS services.

This phase does not include:

- automatic scheduled polling of Indeed;
- periodic automatic disposition flushing;
- operational dashboards/alarms;
- employer registration lifecycle;
- Indeed Partner certification/live E2E.

Those belong to the following automation/observability and certification phases.

## Design principles

1. **Provider URLs are temporary inputs, not durable storage.** The Indeed `resume_url` is consumed by the worker and is never used as the canonical recruiter download URL.
2. **Indeed candidate sync remains fast.** `fetchAssets` persists the candidate/link and a durable resume task, then dispatches asynchronous work. It does not download or evaluate the CV inline.
3. **Reuse existing expensive infrastructure.** Use the current SQS queue, worker service, canonical S3 bucket, Bedrock KB, evaluation service, and ranking service.
4. **Preserve provider neutrality.** Candidate and JobCandidate remain provider-neutral. Resume-processing state belongs to the Indeed adapter.
5. **At-least-once safe.** All operations are resumable/idempotent because SQS may redeliver a message.
6. **No secret URL exposure.** Logs and normal API payloads never return the Indeed pre-signed URL.

## Durable model

Add `IndeedResumeIngestion` with one row per `IndeedCandidateLink`.

Fields:

- `id` UUID PK
- `owner_sub` text, indexed, not null
- `candidate_link_id` UUID FK -> `indeed_candidate_links.id`, unique, cascade delete
- `status` text, not null, default `PENDING`
- `resume_sha256` text nullable
- `canonical_s3_key` text nullable
- `bedrock_ingestion_job_id` text nullable
- `attempt_count` integer, default 0
- `queue_dispatched_at` timestamp nullable
- `processing_token` text nullable
- `heartbeat_at` timestamp nullable
- `last_error_code` text nullable
- `last_error_message` text nullable
- `created_at`, `updated_at`, `completed_at`

Status model:

`PENDING -> DOWNLOADING -> STORED -> INGESTING -> EVALUATING -> RANKING -> COMPLETED`

Terminal failure state:

`FAILED`

Worker retries may resume from the latest durable non-terminal stage.

## SQS envelope

Keep the existing queue and preserve compatibility with existing candidate-import messages.

Existing message remains accepted:

```json
{"schema_version":1,"batch_id":"<uuid>"}
```

New messages are explicit:

```json
{
  "schema_version": 1,
  "kind": "indeed_resume",
  "resume_ingestion_id": "<uuid>"
}
```

The queue adapter returns a typed work item containing `kind`, `identifier`, `receipt_handle`, and `receive_count`.

Existing `send_import_batch()` remains supported. Add `send_indeed_resume_ingestion()`.

The worker routes:

- `candidate_import` -> existing `process_batch()`;
- `indeed_resume` -> new Indeed resume processor.

Invalid/unknown message kinds are ignored safely and are not interpreted as import batches.

## Candidate sync handoff

When a new Indeed asset includes `resume.pdf.url`:

1. create/reuse Candidate;
2. attach JobCandidate;
3. create IndeedCandidateLink;
4. create `IndeedResumeIngestion(PENDING)` in the same database transaction;
5. commit provider/candidate/task state;
6. enqueue the resume ingestion;
7. set `queue_dispatched_at` after successful enqueue.

If enqueue fails, the candidate sync remains durable and returns successfully after recording the task. The worker repair cycle discovers undispatched `PENDING` resume tasks and retries dispatch later.

A repeated Indeed asset does not create a duplicate resume task.

## Secure resume download

Create an Indeed resume downloader isolated from GraphQL transport.

Rules:

- only `https://` URLs are accepted;
- no credentials or bearer tokens are added to the request;
- bounded connect/read timeout;
- maximum downloaded size: **20 MiB**;
- if `Content-Length` exceeds the limit, reject before body download;
- while streaming, abort when the limit is exceeded even when `Content-Length` is absent or incorrect;
- final bytes must begin with PDF magic `%PDF-`;
- empty content is rejected;
- redirects are not followed automatically; an unexpected redirect fails the task rather than sending the pre-signed query string to another host;
- error messages/logs must not contain the full URL/query string.

Output:

```python
DownloadedResume(
    filename: str,
    data: bytes,
    sha256: str,
)
```

The filename is normalized to a `.pdf` name; fallback is `indeed-resume.pdf`.

## Canonical S3 persistence

Reuse `app.infrastructure.imports.storage.write_canonical_candidate_document()`.

Write to the current canonical path:

`documents/cv-{candidate_id}.pdf`

The storage adapter already uses `document-sha256` metadata and returns `changed=False` when the exact canonical document already exists. Persist the returned canonical key and SHA in `IndeedResumeIngestion`.

The provider URL is never returned as the canonical download URL.

## Bedrock ingestion

Generalize the existing ingestion adapter just enough to support a deterministic logical key outside manual batches.

Add a helper such as:

```python
start_ingestion(*, operation_key: str, description: str) -> tuple[str, str]
```

Existing `start_batch_ingestion(batch_id)` delegates to it so current behavior remains unchanged.

Indeed resume operation key:

`indeed-resume:{resume_ingestion_id}:{resume_sha256}`

Persist `bedrock_ingestion_job_id` before polling. Poll existing `get_ingestion_status()` until `COMPLETE`, `FAILED/STOPPED`, or the existing bounded timeout is reached.

If canonical storage reports `changed=False` and this task has already completed the same SHA, the worker is a no-op. Otherwise the worker must still ensure the current document has reached the KB before evaluation.

## Evaluation and ranking

After Bedrock ingestion completes:

1. mark task `EVALUATING`;
2. call the existing owner-scoped `evaluate_candidate_for_owner(candidate_id, job_id, owner_sub)`;
3. use the same bounded transient retry policy as the import worker;
4. require a terminal evaluation result;
5. mark task `RANKING`;
6. call `materialize_ranking_from_evaluations(job_id, owner_sub, scope="assigned")`;
7. persist completion.

An existing completed evaluation may be reused only when the canonical resume SHA did not change. A changed resume must cause a fresh evaluation.

Ranking failures are retryable from the `RANKING` checkpoint and must not redownload/reindex the CV.

## Claiming and retries

Use a durable claim token on `IndeedResumeIngestion`, mirroring the current candidate-import lease concept but kept in the Indeed repository.

- claim only non-terminal tasks whose lease is absent/stale;
- increment `attempt_count` on successful claim;
- refresh heartbeat while active;
- release token after processing;
- SQS message is deleted only after `COMPLETED` or known terminal handling;
- transient exceptions leave the SQS message unacknowledged for redelivery;
- after the existing maximum receive count, mark task `FAILED` with public-safe error code/message and allow SQS/DLQ redrive semantics.

## API contract

Extend the existing candidate Indeed detail endpoint without exposing the provider resume URL:

`GET /api/jobs/{job_id}/candidates/{candidate_id}/integrations/indeed`

Add:

```json
{
  "resume": {
    "name": "ana.pdf",
    "status": "COMPLETED",
    "available": true,
    "sha256": "...",
    "last_error_code": null
  }
}
```

Do not include `resume_url` from Indeed.

Add authenticated endpoint:

`GET /api/jobs/{job_id}/candidates/{candidate_id}/resume`

Behavior:

- owner/job/candidate scoped;
- requires canonical document availability;
- creates a short-lived S3 pre-signed GET URL (5 minutes);
- returns `{ "url": "...", "expires_in": 300 }`;
- never stores the generated URL.

This route is provider-neutral and can later serve manually uploaded candidates too.

## Frontend

CandidateDetail shows:

- source attribution (`Indeed`);
- CV processing state;
- `Ver CV` only when canonical CV is available;
- a processing/error label otherwise.

Clicking `Ver CV` requests the authenticated canonical-resume endpoint, then opens the short-lived returned URL. The browser never receives the original Indeed pre-signed URL.

## Error semantics

Durable error codes include:

- `RESUME_URL_MISSING`
- `RESUME_URL_INVALID`
- `RESUME_DOWNLOAD_FAILED`
- `RESUME_TOO_LARGE`
- `RESUME_NOT_PDF`
- `CANONICAL_STORAGE_FAILED`
- `BEDROCK_INGESTION_FAILED`
- `BEDROCK_INGESTION_TIMEOUT`
- `EVALUATION_FAILED`
- `RANKING_FAILED`
- `RETRY_EXHAUSTED`

Persist only sanitized/public-safe messages. Provider URLs, query strings, AWS response bodies, or OAuth secrets are never persisted as error text.

## Testing

All external boundaries are mocked.

Tests cover:

- model/migration 006 and PostgreSQL migration head;
- creation/idempotency of resume tasks during candidate sync;
- queue backward compatibility plus new typed message;
- undispatched task repair;
- HTTPS-only URL validation;
- no redirects;
- content-length and streamed 20 MiB limit;
- PDF magic validation;
- SHA calculation;
- canonical storage idempotency;
- worker resume from durable stages;
- Bedrock ingestion success/failure/timeout;
- evaluation only when required;
- ranking after terminal evaluation;
- retry/DLQ behavior;
- tenant isolation;
- API never exposes original provider URL;
- canonical pre-signed GET route;
- CandidateDetail states and `Ver CV` interaction.

## Deployment/cost

No new AWS service is introduced. This phase reuses the existing queue, worker, S3 bucket, Bedrock KB, database, and frontend deployment. Incremental cost is only normal SQS/S3/Bedrock usage for Indeed candidates.
