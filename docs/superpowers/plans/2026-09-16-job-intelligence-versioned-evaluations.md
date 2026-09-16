# Job Intelligence and Versioned Evaluations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe job editing, version-aware evaluation reuse, durable candidate reevaluation, and AI-assisted vacancy enrichment without wasting Bedrock calls.

**Architecture:** Jobs gain an explicit evaluation version and structured evaluation profile. Evaluations persist the job version they were computed against, and the central evaluation service becomes the single freshness gate. Evaluation-relevant job changes schedule durable reevaluation work on the existing shared queue, while enrichment is advisory and only changes persistence after HR applies and saves the proposal.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite tests, existing SQS worker dispatcher, existing Bedrock evaluation stack, React/Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-16-job-intelligence-versioned-evaluations-design.md`

## Global Constraints

- Do not introduce a second queue.
- Do not modify Gmail OAuth/mailbox synchronization during this feature block.
- Do not deploy new AWS infrastructure during this feature block.
- Preserve `owner_sub` tenant isolation in every persisted read/write.
- A current completed evaluation must be reused without retrieval or LLM invocation.
- Only title, description, and `evaluation_profile` invalidate evaluations.
- `public_slug`, `published_at`, `country_code`, `city`, and `employment_type` alone do not invalidate evaluations.
- Enrichment is advisory and never persists automatically.
- A version-changing save schedules reevaluation asynchronously; the HTTP request never loops through all candidates.

---

## File Structure

### New files

- `app/migrations/versions/008_job_intelligence.py` — schema changes for job/evaluation versioning and durable reevaluation tasks.
- `app/domains/jobs/profile.py` — normalization/comparison of evaluation-relevant job content.
- `app/domains/jobs/enrichment.py` — strict structured vacancy enrichment orchestration.
- `app/domains/jobs/reevaluation.py` — durable task creation/claim/checkpoint logic.
- `app/workers/job_reevaluations.py` — worker handler for reevaluating assigned candidates and rebuilding ranking.
- `app/tests/test_job_versioning.py` — backend version invalidation rules.
- `app/tests/test_evaluation_freshness.py` — reuse/stale/force evaluation contracts.
- `app/tests/test_job_reevaluation_worker.py` — queue/worker idempotency and tenant behavior.
- `app/tests/test_job_enrichment.py` — structured enrichment behavior and failure safety.
- `frontend-react/src/__tests__/Jobs.intelligence.test.jsx` — non-invasive warning and enrichment UX.

### Modified files

- `app/models.py` — add Job/Evaluation fields and `JobReevaluationTask` model.
- `app/domains/jobs/schemas.py` — structured profile/enrichment/update response schemas.
- `app/domains/jobs/repository.py` — version-aware update helpers and candidate counts.
- `app/domains/jobs/service.py` — normalized diff, version bump, task scheduling, enriched response metadata.
- `app/domains/jobs/presenter.py` — expose version/profile/update metadata.
- `app/domains/jobs/router.py` — `POST /api/jobs/enrich` and richer update response.
- `app/domains/evaluations/repository.py` — current-version freshness rule and version persistence.
- `app/domains/evaluations/service.py` — central reuse gate and `force` option.
- `app/domains/evaluations/presenter.py` — expose `job_evaluation_version` when useful for diagnostics/API consistency.
- `app/workers/dispatcher.py` — route `job_reevaluation` work kind to the new handler.
- `app/domains/ranking/service.py` — reuse existing ranking regeneration entry point from the worker; only add a thin callable if no suitable public function exists.
- `app/tests/test_postgres_migrations.py` — assert migration head `008`, columns, and task table.
- `frontend-react/src/pages/Jobs.jsx` — warning, enrichment action/review, update result messaging.
- `frontend-react/src/pages/Jobs.css` — compact inline notice/proposal styling.

---

### Task 1: Migration 008 and persistence contracts

**Files:**
- Create: `app/migrations/versions/008_job_intelligence.py`
- Modify: `app/models.py`
- Modify: `app/tests/test_postgres_migrations.py`
- Create: `app/tests/test_job_versioning.py`

**Interfaces:**
- Produces `Job.evaluation_version: int`, `Job.evaluation_profile: dict`, `Job.updated_at: datetime`.
- Produces `Evaluation.job_evaluation_version: int`.
- Produces `JobReevaluationTask` with unique `(job_id, target_evaluation_version)`.

- [ ] **Step 1: Write failing ORM and migration tests**

Add tests that instantiate/read the new ORM fields and extend PostgreSQL smoke assertions:

```python
job_columns = {column["name"] for column in inspector.get_columns("jobs")}
assert {"evaluation_version", "evaluation_profile", "updated_at"}.issubset(job_columns)

evaluation_columns = {
    column["name"] for column in inspector.get_columns("evaluations")
}
assert "job_evaluation_version" in evaluation_columns

assert "job_reevaluation_tasks" in tables
assert revision == "008"
```

Also test model defaults:

```python
job = Job(title="Cloud Engineer", owner_sub="owner-1")
assert job.evaluation_version in (None, 1)  # before/after flush semantics
```

- [ ] **Step 2: Run targeted tests and confirm RED**

Run:

```bash
python -m pytest app/tests/test_job_versioning.py app/tests/test_postgres_migrations.py -v --tb=short
```

Expected: failures due to missing fields/revision/table.

- [ ] **Step 3: Implement ORM model fields**

Add to `Job`:

```python
evaluation_version = Column(Integer, nullable=False, default=1)
evaluation_profile = Column(JSON, nullable=False, default=dict)
updated_at = Column(
    DateTime(timezone=True),
    nullable=False,
    default=lambda: datetime.now(timezone.utc),
    onupdate=lambda: datetime.now(timezone.utc),
)
```

Add to `Evaluation`:

```python
job_evaluation_version = Column(Integer, nullable=False, default=1)
```

Add `JobReevaluationTask` with the exact durable fields from the spec and:

```python
__table_args__ = (
    UniqueConstraint(
        "job_id",
        "target_evaluation_version",
        name="uq_job_reevaluation_job_version",
    ),
    Index("idx_job_reevaluation_owner_created", "owner_sub", "created_at"),
    Index("idx_job_reevaluation_status_heartbeat", "status", "heartbeat_at"),
)
```

- [ ] **Step 4: Implement Alembic revision 008**

Revision metadata:

```python
revision = "008"
down_revision = "007"
```

Upgrade must add/backfill the columns and create `job_reevaluation_tasks`. Existing jobs/evaluations become version `1`. Use PostgreSQL-safe JSON defaults/backfill and remove transient server defaults after backfill where appropriate.

- [ ] **Step 5: Run targeted tests and confirm GREEN**

Run the same targeted test command; then allow CI PostgreSQL smoke to verify the real migration.

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/migrations/versions/008_job_intelligence.py app/tests/test_job_versioning.py app/tests/test_postgres_migrations.py
git commit -m "feat: version job evaluation profiles"
```

---

### Task 2: Central evaluation freshness gate

**Files:**
- Create: `app/tests/test_evaluation_freshness.py`
- Modify: `app/domains/evaluations/repository.py`
- Modify: `app/domains/evaluations/service.py`
- Modify: `app/domains/evaluations/presenter.py`

**Interfaces:**
- Produces `is_evaluation_current(evaluation, job) -> bool`.
- Extends `evaluate_candidate_for_job(..., force: bool = False)`.
- Extends `evaluate_candidate_for_owner(..., force: bool = False)`.
- `create_evaluation(..., job_evaluation_version: int)` persists the source job version.

- [ ] **Step 1: Write RED tests for reuse, stale, failed and force cases**

Use monkeypatched retrieval/LLM functions with counters:

```python
def test_current_completed_evaluation_is_reused_without_llm(...):
    existing.job_evaluation_version = job.evaluation_version
    result, newly_evaluated, error = evaluate_candidate_for_job(
        db, candidate=candidate, job=job
    )
    assert result.id == existing.id
    assert newly_evaluated is False
    assert error is None
    assert retrieve_calls == 0
    assert llm_calls == 0
```

Add tests proving stale version, failed/incomplete evaluation, and `force=True` do invoke evaluation.

- [ ] **Step 2: Run tests and confirm RED**

```bash
python -m pytest app/tests/test_evaluation_freshness.py -v --tb=short
```

Expected: current evaluation still invokes backend or helpers/signatures are missing.

- [ ] **Step 3: Implement repository freshness**

Add:

```python
def is_evaluation_current(evaluation: Evaluation | None, job) -> bool:
    return (
        is_evaluation_complete(evaluation)
        and evaluation.job_evaluation_version == job.evaluation_version
    )
```

Update `needs_evaluation` to accept the job or replace callers with the explicit current check while preserving failed/incomplete semantics.

- [ ] **Step 4: Implement central short-circuit before retrieval**

At the start of `evaluate_candidate_for_job`:

```python
existing = evaluations_repository.get_evaluation_for_job_candidate(
    db, job.id, candidate.id
)
if not force and evaluations_repository.is_evaluation_current(existing, job):
    return existing, False, None
```

Every successful/failed persistence call must include:

```python
job_evaluation_version=job.evaluation_version
```

- [ ] **Step 5: Run freshness + existing evaluation suite**

```bash
python -m pytest app/tests/test_evaluation_freshness.py app/tests/test_evaluation_service.py -v --tb=short
```

If `test_evaluation_service.py` has a different existing filename, run the existing evaluation test module(s) discovered in `app/tests/` together with the new file.

- [ ] **Step 6: Commit**

```bash
git add app/domains/evaluations app/tests/test_evaluation_freshness.py
git commit -m "feat: reuse current candidate evaluations"
```

---

### Task 3: Job profile normalization, version bump and durable reevaluation scheduling

**Files:**
- Create: `app/domains/jobs/profile.py`
- Create: `app/domains/jobs/reevaluation.py`
- Modify: `app/domains/jobs/schemas.py`
- Modify: `app/domains/jobs/repository.py`
- Modify: `app/domains/jobs/service.py`
- Modify: `app/domains/jobs/presenter.py`
- Modify: `app/domains/jobs/router.py`
- Extend: `app/tests/test_job_versioning.py`

**Interfaces:**
- Produces `normalize_evaluation_profile(profile: dict | None) -> dict`.
- Produces `evaluation_signature(title, description, profile) -> tuple` or equivalent normalized comparison object.
- Produces `schedule_reevaluation(db, *, job, owner_sub) -> JobReevaluationTask | None`.
- `update_job` returns enough metadata to produce `evaluation_changed`, `reevaluation_scheduled`, and `reevaluation_candidate_count`.

- [ ] **Step 1: Write RED tests for relevant vs metadata-only changes**

Test cases:

```python
@pytest.mark.parametrize("field", ["title", "description", "evaluation_profile"])
def test_evaluation_relevant_change_increments_version(field, ...): ...

@pytest.mark.parametrize(
    "field",
    ["public_slug", "published_at", "country_code", "city", "employment_type"],
)
def test_metadata_change_does_not_increment_version(field, ...): ...

def test_identical_normalized_content_does_not_increment_version(...): ...
```

Also prove only one task is created for the same `(job_id, target_version)`.

- [ ] **Step 2: Run targeted tests and confirm RED**

```bash
python -m pytest app/tests/test_job_versioning.py -v --tb=short
```

- [ ] **Step 3: Add strict Pydantic evaluation profile schema**

Define profile fields exactly as in the spec with safe `default_factory=list`. Add optional `evaluation_profile` to create/update requests and version/profile fields to responses.

- [ ] **Step 4: Implement normalized comparison**

Normalize whitespace and profile list values deterministically enough that resubmitting equivalent content does not create a new version. Do not alphabetically reorder fields where order carries recruiter intent unless comparison tests establish order-insensitive semantics for that specific field.

- [ ] **Step 5: Implement version-aware update transaction**

`service.update_job` must:

1. load tenant-owned job;
2. snapshot old normalized evaluation signature;
3. apply requested fields;
4. compute new normalized signature;
5. increment `evaluation_version` exactly once only if signatures differ;
6. persist job;
7. count assigned candidates;
8. create/get the durable task only when evaluation changed and candidate count > 0;
9. return metadata without running evaluations synchronously.

- [ ] **Step 6: Implement idempotent task repository/service**

`reevaluation.py` uses the unique job/version constraint and returns an existing task on duplicate scheduling rather than raising to the API.

- [ ] **Step 7: Expose update metadata through presenter/router**

Return:

```json
{
  "evaluation_version": 4,
  "evaluation_profile": {},
  "evaluation_changed": true,
  "reevaluation_scheduled": true,
  "reevaluation_candidate_count": 18
}
```

- [ ] **Step 8: Run targeted job/evaluation tests**

```bash
python -m pytest app/tests/test_job_versioning.py app/tests/test_evaluation_freshness.py -v --tb=short
```

- [ ] **Step 9: Commit**

```bash
git add app/domains/jobs app/tests/test_job_versioning.py
git commit -m "feat: schedule reevaluation when job profile changes"
```

---

### Task 4: Shared-queue reevaluation worker and ranking regeneration

**Files:**
- Create: `app/workers/job_reevaluations.py`
- Modify: `app/workers/dispatcher.py`
- Modify: `app/domains/jobs/reevaluation.py`
- Modify only if needed: `app/domains/ranking/service.py`
- Create: `app/tests/test_job_reevaluation_worker.py`

**Interfaces:**
- Adds shared queue work kind `job_reevaluation`.
- Produces `process_job_reevaluation(db, *, task_id: str, ...)` or dispatcher-compatible equivalent.
- Uses the central evaluation service; never directly calls the LLM.

- [ ] **Step 1: Write RED worker tests**

Cover:

```python
def test_worker_evaluates_only_stale_candidates(...): ...
def test_worker_retry_does_not_duplicate_current_evaluations(...): ...
def test_older_task_cannot_overwrite_newer_job_version(...): ...
def test_worker_marks_task_completed_and_regenerates_ranking(...): ...
def test_worker_is_tenant_scoped(...): ...
```

- [ ] **Step 2: Run worker tests and confirm RED**

```bash
python -m pytest app/tests/test_job_reevaluation_worker.py -v --tb=short
```

- [ ] **Step 3: Add dispatcher work kind**

Follow the existing dispatcher pattern used by candidate imports/ingestions and Indeed resumes. Add only the new route; reuse the existing queue and DLQ.

- [ ] **Step 4: Implement claim/checkpoint/retry behavior**

Use the same durable conventions already present in existing workers: processing token, heartbeat, attempt count, terminal completion/failure fields, and existing maximum delivery/DLQ behavior.

- [ ] **Step 5: Evaluate candidates via the central freshness gate**

For each assigned candidate:

```python
evaluation, newly_evaluated, _ = evaluate_candidate_for_job(
    db,
    candidate=candidate,
    job=current_job,
)
```

Do not pass `force=True`; the worker must naturally skip candidates already current on the latest version.

- [ ] **Step 6: Regenerate ranking once after the batch**

Call the existing ranking orchestration entry point after processing assigned candidates. If no suitable public function exists, expose a thin `regenerate_ranking_for_job(...)` wrapper in `app/domains/ranking/service.py` around the existing ranking logic rather than duplicating ranking code.

- [ ] **Step 7: Run worker + dispatcher regression tests**

```bash
python -m pytest app/tests/test_job_reevaluation_worker.py app/tests/ -k "dispatcher or candidate_ingestion or indeed_resume" -v --tb=short
```

- [ ] **Step 8: Commit**

```bash
git add app/workers app/domains/jobs/reevaluation.py app/domains/ranking/service.py app/tests/test_job_reevaluation_worker.py
git commit -m "feat: reevaluate job candidates asynchronously"
```

---

### Task 5: AI vacancy enrichment endpoint

**Files:**
- Create: `app/domains/jobs/enrichment.py`
- Modify: `app/domains/jobs/schemas.py`
- Modify: `app/domains/jobs/router.py`
- Create: `app/tests/test_job_enrichment.py`

**Interfaces:**
- Produces `JobEnrichmentRequest` from an unsaved job draft.
- Produces validated `JobEnrichmentProposal`.
- Produces `enrich_job_draft(request, *, model_client=None) -> JobEnrichmentProposal`.
- Endpoint: `POST /api/jobs/enrich`.

- [ ] **Step 1: Write RED schema/service/API tests**

Prove:

```python
def test_enrichment_returns_structured_required_and_preferred_requirements(...): ...
def test_enrichment_does_not_mutate_existing_job(...): ...
def test_malformed_model_payload_returns_controlled_error(...): ...
def test_enrichment_does_not_use_candidate_data(...): ...
```

- [ ] **Step 2: Run enrichment tests and confirm RED**

```bash
python -m pytest app/tests/test_job_enrichment.py -v --tb=short
```

- [ ] **Step 3: Define strict request/response schemas**

Use `Field(default_factory=list)` for list fields and forbid/ignore extra model fields according to the project's current Pydantic conventions. Required vs preferred technology/certification fields remain distinct.

- [ ] **Step 4: Implement the enrichment prompt and model adapter**

The prompt must explicitly say:

```text
- Do not invent organization-specific tooling as fact.
- Put uncertain organization-specific assumptions in assumptions_to_validate.
- Separate required from preferred technologies and certifications.
- Do not use protected-class or unrelated personal attributes.
- Return JSON only matching the response schema.
```

Reuse the project's existing Bedrock runtime/model configuration rather than introducing another provider abstraction. Dependency-inject the model call for tests.

- [ ] **Step 5: Validate model output before returning**

Parse JSON and instantiate `JobEnrichmentProposal`. On malformed/invalid output raise a domain exception mapped by the router to a controlled HTTP error; never write to `jobs`.

- [ ] **Step 6: Add authenticated endpoint**

`POST /api/jobs/enrich` uses `get_current_user` for authentication but receives only draft data. It does not need a job ID and performs no database mutation.

- [ ] **Step 7: Run tests and commit**

```bash
python -m pytest app/tests/test_job_enrichment.py -v --tb=short
git add app/domains/jobs app/tests/test_job_enrichment.py
git commit -m "feat: enrich vacancy profiles with ai"
```

---

### Task 6: Non-invasive Jobs UI for warnings and enrichment review

**Files:**
- Modify: `frontend-react/src/pages/Jobs.jsx`
- Modify: `frontend-react/src/pages/Jobs.css`
- Create: `frontend-react/src/__tests__/Jobs.intelligence.test.jsx`

**Interfaces:**
- Consumes update response fields from Task 3.
- Consumes `POST /api/jobs/enrich` from Task 5.
- Never auto-saves an enrichment proposal.

- [ ] **Step 1: Write RED frontend tests**

Test that editing a job with candidates shows the inline informational copy:

```text
Esta vacante tiene candidatos evaluados. Los cambios en el perfil harán que sus evaluaciones se actualicen automáticamente.
```

Also test:

- enrichment button calls `/jobs/enrich`;
- proposal is rendered before application;
- applying a proposal changes local form state only;
- submit remains the persistence action;
- a version-changing response displays pending reevaluation count;
- metadata-only response does not claim reevaluation.

- [ ] **Step 2: Run Vitest and confirm RED**

```bash
cd frontend-react
npx vitest run src/__tests__/Jobs.intelligence.test.jsx
```

- [ ] **Step 3: Add compact inline edit warning**

Render a small `role="note"` block near form actions only when editing and the job has candidates/evaluations to be affected. No modal and no checkbox.

- [ ] **Step 4: Add enrichment button and loading/error state**

Button label: `Enriquecer con IA`. Disable only while its own request is active; do not block ordinary manual editing.

- [ ] **Step 5: Add proposal review UI**

Show improved description and structured fields in a compact review panel. `Aplicar propuesta` copies proposal values into editable form state; `Descartar` closes it. Neither action calls PUT/POST job persistence.

- [ ] **Step 6: Add save feedback**

If update response contains `reevaluation_scheduled: true`, show:

```text
Perfil actualizado · reevaluación de N candidatos pendiente
```

Otherwise use normal success copy.

- [ ] **Step 7: Run frontend tests/lint/build**

```bash
cd frontend-react
npx vitest run
npm run lint
npm run build
```

- [ ] **Step 8: Commit**

```bash
git add frontend-react/src/pages/Jobs.jsx frontend-react/src/pages/Jobs.css frontend-react/src/__tests__/Jobs.intelligence.test.jsx
git commit -m "feat: add intelligent vacancy editing ux"
```

---

### Task 7: Full regression verification and Gmail continuation gate

**Files:**
- Modify only if verification exposes a real issue: affected implementation/test files.
- No AWS infrastructure changes in this task.

**Interfaces:**
- Confirms migration head `008`.
- Confirms the PR still uses a single PR validation workflow.
- Leaves the next work item as Google OAuth personal Gmail + AWS Secrets Manager.

- [ ] **Step 1: Run full backend test suite**

```bash
python -m pytest app/tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend full verification**

```bash
cd frontend-react
npm run lint
npx vitest run
npm run build
```

Expected: all pass.

- [ ] **Step 3: Push and verify GitHub Actions**

Require all PR checks:

- Backend tests (pytest): success
- Frontend lint/test/build: success
- Backend smoke (Postgres): success
- Alembic head: `008`

Confirm `CI/CD — Tests & Deploy` does not run for the PR.

- [ ] **Step 4: Inspect final PR diff for scope**

Verify no Gmail OAuth secrets, passwords, refresh tokens, AWS secret values, or unrelated infrastructure changes entered the branch.

- [ ] **Step 5: Mark continuation point**

After green verification, resume exactly at:

```text
Google OAuth personal Gmail
→ real refresh token
→ AWS Secrets Manager us-east-2
→ API/worker runtime configuration
→ real Indeed notification email
→ end-to-end Gmail ingestion test
```

- [ ] **Step 6: Final checkpoint commit only if verification required fixes**

Use a narrowly-scoped message matching the actual fix; do not create an empty verification commit.
