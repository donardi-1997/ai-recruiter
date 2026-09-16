# Candidate Email Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-ready candidate ingestion path from normalized email events into the existing S3/SQS/Bedrock/evaluation/ranking pipeline.

**Architecture:** Introduce provider-neutral `CandidateIngestionEvent` and `CandidateIngestionDocument` persistence, then route typed `candidate_ingestion` work through the shared queue. Email remains an adapter: it normalizes provider messages and stores attachments before handing off to the core. Existing bulk import and Indeed resume flows remain intact while the new core is proven.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite tests, AWS S3, SQS, Bedrock, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-candidate-ingestion-core-design.md`

## Global Constraints

- Branch is based on the current Indeed resume-ingestion work; Alembic migration must be `007` revising `006`.
- Core domain must not import Gmail or Indeed modules.
- Email V1 accepts PDF and DOCX only; existing 15 MiB per-document limit applies.
- Automatic job selection must be conservative; ambiguous or missing job context becomes `NEEDS_REVIEW`.
- Tenant ownership must be enforced for every job and candidate relation.
- Existing candidate import and Indeed contracts must remain compatible.
- Durable DB state is committed before SQS dispatch; queue repair must cover committed-but-undispatched events.
- TDD is mandatory for behavior changes.

---

### Task 1: Provider-neutral ingestion persistence

**Files:**
- Create: `app/domains/candidate_ingestion/__init__.py`
- Create: `app/domains/candidate_ingestion/models.py`
- Create: `app/migrations/versions/007_candidate_ingestion_core.py`
- Create: `app/tests/test_candidate_ingestion_models.py`
- Modify: `app/tests/test_postgres_migrations.py`

**Interfaces:**
- Produces: `CandidateIngestionEvent` and `CandidateIngestionDocument` ORM models.
- `CandidateIngestionEvent` uniquely identifies external machine events by `(owner_sub, source, provider, external_id)`.
- A job and candidate are nullable at receipt time.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_ingestion_event_supports_unresolved_email_event(db_session):
    event = CandidateIngestionEvent(
        owner_sub="owner-1",
        source="EMAIL",
        provider="INDEED",
        external_id="gmail-message-1",
        status="RECEIVED",
    )
    db_session.add(event)
    db_session.commit()
    assert event.job_id is None
    assert event.candidate_id is None


def test_ingestion_external_event_is_idempotent_per_owner_source_provider(db_session):
    # insert same owner/source/provider/external_id twice
    # second commit must raise IntegrityError
    ...
```

Also update PostgreSQL smoke expectations for tables `candidate_ingestion_events` and `candidate_ingestion_documents`, and expected Alembic head `007`.

- [ ] **Step 2: Verify RED in GitHub Actions**

Expected failure: import/migration/table assertions fail because the models and migration do not exist.

- [ ] **Step 3: Implement minimal ORM models and migration**

`CandidateIngestionEvent` fields: `id`, `owner_sub`, `source`, `provider`, `external_id`, nullable `job_id`, nullable `candidate_id`, `status`, `raw_metadata`, nullable `raw_s3_key`, `queue_dispatched_at`, `processing_token`, `heartbeat_at`, `attempt_count`, `last_error_code`, `last_error_message`, timestamps.

`CandidateIngestionDocument` fields: `id`, `ingestion_event_id`, `filename`, `content_type`, `size_bytes`, `source_s3_key`, nullable `document_sha256`, nullable `canonical_s3_key`, `status`, `error_code`, `error_message`, timestamps.

- [ ] **Step 4: Verify GREEN**

Run full backend tests and PostgreSQL migration smoke in Actions.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add candidate ingestion persistence"
```

### Task 2: Ingestion repository, validation, and idempotent service

**Files:**
- Create: `app/domains/candidate_ingestion/exceptions.py`
- Create: `app/domains/candidate_ingestion/rules.py`
- Create: `app/domains/candidate_ingestion/repository.py`
- Create: `app/domains/candidate_ingestion/service.py`
- Create: `app/tests/test_candidate_ingestion_domain.py`

**Interfaces:**
- Produces `service.create_ingestion_event(db, *, owner_sub, source, provider, external_id, documents, job_id=None, raw_metadata=None, raw_s3_key=None) -> tuple[CandidateIngestionEvent, bool]`, where bool is `created`.
- Produces owner-scoped get/list helpers and durable undispatched lookup.

- [ ] **Step 1: Write failing tests for idempotency, tenant isolation, nullable job, owned job validation, PDF/DOCX validation, and duplicate external ids**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement minimal rules/repository/service**
- [ ] **Step 4: Verify GREEN plus candidate-import regressions**
- [ ] **Step 5: Commit** with `feat: add candidate ingestion domain service`.

### Task 3: Shared SQS contract and dispatch repair

**Files:**
- Modify: `app/infrastructure/imports/queue.py`
- Modify: `app/workers/dispatcher.py`
- Create: `app/workers/candidate_ingestion.py`
- Modify: `app/tests/test_candidate_import_infrastructure.py`
- Modify: `app/tests/test_worker_dispatcher.py`
- Create: `app/tests/test_candidate_ingestion_worker.py`

**Interfaces:**
- Adds `CANDIDATE_INGESTION_KIND = "candidate_ingestion"`.
- Adds `queue.send_candidate_ingestion(ingestion_event_id)` with payload `{schema_version: 1, kind: "candidate_ingestion", ingestion_event_id: <id>}`.
- Dispatcher routes this kind to `candidate_ingestion.handle_message`.
- Existing legacy and Indeed payloads remain valid.

- [ ] **Step 1: Write failing queue and dispatcher tests**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement serialization/deserialization, dispatcher route, and undispatched repair**
- [ ] **Step 4: Verify GREEN, including legacy queue tests**
- [ ] **Step 5: Commit** with `feat: route candidate ingestion work through shared queue`.

### Task 4: Provider-neutral processing worker

**Files:**
- Modify: `app/workers/candidate_ingestion.py`
- Modify: `app/domains/candidate_imports/service.py` only to extract a provider-neutral candidate-resolution helper if required without changing public import behavior.
- Modify/Create tests in `app/tests/test_candidate_ingestion_worker.py`.

**Interfaces:**
- `process_ingestion(event_id)` claims a lease and resumes from durable state.
- Reads the source S3 document, parses through `app.infrastructure.imports.documents.extract_document`, resolves strong identity, assigns the owned job, writes canonical CV, triggers Bedrock, evaluation, then ranking.
- Missing/ambiguous job stops at `NEEDS_REVIEW` before candidate-job assignment/evaluation.

- [ ] **Step 1: Write happy-path and checkpoint-resume failing tests**
- [ ] **Step 2: Write failing test proving missing job becomes `NEEDS_REVIEW` and does not evaluate**
- [ ] **Step 3: Verify RED**
- [ ] **Step 4: Implement minimal worker using existing primitives**
- [ ] **Step 5: Verify GREEN plus existing Indeed and candidate-import worker suites**
- [ ] **Step 6: Commit** with `feat: process provider-neutral candidate ingestions`.

### Task 5: Email adapter and Indeed email normalization

**Files:**
- Create: `app/integrations/email_ingestion/__init__.py`
- Create: `app/integrations/email_ingestion/schemas.py`
- Create: `app/integrations/email_ingestion/parser.py`
- Create: `app/integrations/email_ingestion/service.py`
- Create: `app/integrations/email_ingestion/providers/__init__.py`
- Create: `app/integrations/email_ingestion/providers/indeed.py`
- Create: `app/integrations/email_ingestion/providers/generic.py`
- Create: `app/tests/test_email_ingestion.py`

**Interfaces:**
- `EmailEnvelope(message_id, sender, recipients, subject, body_text, received_at, attachments)` is transport-neutral.
- Provider detection returns `INDEED` only for trusted configured Indeed sender patterns; otherwise `GENERIC_EMAIL`/review path.
- Adapter stores only PDF/DOCX attachment descriptors and invokes Candidate Ingestion Core using `message_id` as `external_id`.

- [ ] **Step 1: Write failing tests for trusted Indeed detection, PDF/DOCX acceptance, duplicate message id, and untrusted sender behavior**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement minimal transport-neutral parser/service**
- [ ] **Step 4: Verify GREEN**
- [ ] **Step 5: Commit** with `feat: add email candidate ingestion adapter`.

### Task 6: Owner-scoped visibility and manual job resolution

**Files:**
- Create: `app/domains/candidate_ingestion/schemas.py`
- Create: `app/domains/candidate_ingestion/presenter.py`
- Create: `app/domains/candidate_ingestion/router.py`
- Modify bootstrap/router registration following existing modular patterns.
- Create: `app/tests/test_candidate_ingestion_api.py`

**Interfaces:**
- `GET /candidate-ingestions`
- `GET /candidate-ingestions/{id}`
- `POST /candidate-ingestions/{id}/resolve-job`
- Retry endpoint only if semantics are fully covered by worker state tests.

- [ ] **Step 1: Write failing owner-scope and resolve-job API tests**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement minimal API**
- [ ] **Step 4: Verify GREEN plus contract tests**
- [ ] **Step 5: Commit** with `feat: expose candidate ingestion review API`.

### Task 7: Gmail/Workspace transport

**Files:**
- Create a transport adapter under `app/integrations/email_ingestion/gmail.py` plus focused tests and environment documentation.

**Interfaces:**
- Incremental mailbox reader persists Gmail `message.id` as ingestion `external_id`.
- Mailbox transport produces `EmailEnvelope`; it does not contain candidate-domain logic.
- Durable Gmail cursor prevents full-mailbox rescans.

- [ ] **Step 1: Write failing transport tests around message normalization and cursor behavior using fake Gmail responses**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement Gmail transport without exposing credentials to frontend**
- [ ] **Step 4: Verify GREEN**
- [ ] **Step 5: Commit** with `feat: ingest candidate emails from workspace mailbox`.

### Task 8: Full verification and production readiness

- [ ] Run full backend pytest.
- [ ] Run contract tests.
- [ ] Run frontend lint/test/build to prove no regression.
- [ ] Run PostgreSQL/Alembic smoke and assert revision `007`.
- [ ] Verify no secret/mailbox credentials are committed.
- [ ] Verify existing Indeed resume and bulk import tests remain green.
- [ ] Review diff for source/provider coupling and public-safe error messages.
