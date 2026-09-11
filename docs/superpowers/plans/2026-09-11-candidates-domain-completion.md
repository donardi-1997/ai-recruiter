# Candidates Domain Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Candidates domain off `app.crud` and move orchestration/presentation out of its FastAPI router without changing public behavior.

**Architecture:** Keep candidate SQL in the existing repository, introduce a FastAPI-free application service and pure presenter, and map domain exceptions to the existing HTTP errors in the router. Cross-domain repository reads for Jobs/Evaluations remain explicitly transitional in this focused PR.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2.0, pytest, PostgreSQL/SQLite, existing storage infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-11-candidates-domain-completion-design.md`

## Global Constraints

- Preserve every existing Candidates and job-candidate route, payload, status code, and Spanish public error string.
- Preserve owner/tenant isolation.
- Preserve candidate-create-before-index behavior for bulk uploads.
- Do not modify models, Alembic migrations, Bedrock logic, deployment topology, or frontend files.
- Keep `app/crud.py` until all other domains migrate.
- Every implementation step must be preceded by a failing focused test and followed by the full relevant regression suite.

---

### Task 1: Add Candidates boundary characterization

**Files:**
- Create: `app/tests/test_candidates_domain.py`
- Modify: `app/tests/test_architecture_boundaries.py`

**Interfaces:**
- Consumes: existing candidate repository/models and current HTTP contracts.
- Produces: executable contracts for presenter/service functions and an architecture rule that Candidates may no longer import `app.crud` after Task 5.

- [ ] **Step 1: Add presenter/service contract tests that initially fail because the modules do not exist**

Cover these exact behaviors:

```python
from app.domains.candidates import presenter, service


def test_candidate_to_dict_preserves_public_shape(candidate):
    data = presenter.candidate_to_dict(candidate)
    assert data["candidate_id"] == candidate.id
    assert data["id"] == candidate.id
    assert data["filename"] == candidate.metadata_.get("filename")


def test_failed_evaluation_is_sanitized(failed_evaluation):
    data = presenter.evaluation_to_dict(failed_evaluation)
    assert data["match_score"] is None
    assert data["recommendation"] == "EVALUATION_FAILED"
    assert data["error_message"] == "No fue posible completar la evaluación. Intenta nuevamente."
```

Add focused service tests with monkeypatched repositories for:

```python
def test_require_candidate_raises_candidate_not_found(monkeypatch, db):
    monkeypatch.setattr(service.candidates_repository, "get_candidate", lambda *a, **k: None)
    with pytest.raises(service.CandidateNotFound):
        service.require_candidate(db, "missing", "owner")


def test_require_job_raises_job_not_found(monkeypatch, db):
    monkeypatch.setattr(service.jobs_repository, "get_job", lambda *a, **k: None)
    with pytest.raises(service.JobNotFound):
        service.require_job(db, "missing", "owner")
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m pytest app/tests/test_candidates_domain.py -v --tb=short
```

Expected: import failure for missing Candidates `presenter`/`service`.

- [ ] **Step 3: Do not shrink the CRUD allow-list yet**

Keep `domains/candidates/router.py` temporarily allow-listed until router migration is complete; this keeps the architecture test truthful during intermediate commits.

- [ ] **Step 4: Commit the characterization tests**

```bash
git add app/tests/test_candidates_domain.py
git commit -m "test: characterize candidates domain boundary"
```

---

### Task 2: Introduce domain exceptions and pure presenter

**Files:**
- Create: `app/domains/candidates/exceptions.py`
- Create: `app/domains/candidates/presenter.py`
- Test: `app/tests/test_candidates_domain.py`

**Interfaces:**
- Produces: `CandidateNotFound`, `JobNotFound`, `candidate_to_dict`, `evaluation_to_dict`, `evaluation_explanation_to_dict`, `evaluation_requirements_to_dict`.

- [ ] **Step 1: Implement exceptions**

```python
class CandidateNotFound(Exception):
    """Requested candidate is not visible to the current owner."""


class JobNotFound(Exception):
    """Requested job is not visible to the current owner."""
```

- [ ] **Step 2: Implement presenter with exact compatibility constant**

```python
FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)
```

`candidate_to_dict(candidate)` must return exactly the current candidate keys: `candidate_id`, `id`, `name`, `email`, `created_at`, `metadata`, `filename`.

`evaluation_to_dict(evaluation)` must preserve the current FAILED masking semantics. `evaluation_explanation_to_dict(None)` must return `PENDING / Sin evaluacion.`. `evaluation_requirements_to_dict` must prefer structured `evaluation.requirements`, otherwise map strengths to `MATCH` and gaps to `MISSING` with `evidence: None`.

- [ ] **Step 3: Run presenter tests and verify GREEN**

```bash
python -m pytest app/tests/test_candidates_domain.py -v --tb=short
```

The presenter tests pass; service tests may still fail until Task 3.

- [ ] **Step 4: Commit**

```bash
git add app/domains/candidates/exceptions.py app/domains/candidates/presenter.py app/tests/test_candidates_domain.py
git commit -m "refactor: add candidates presentation boundary"
```

---

### Task 3: Add Candidates application service for reads, assignments and deletes

**Files:**
- Create: `app/domains/candidates/service.py`
- Test: `app/tests/test_candidates_domain.py`

**Interfaces:**
- Produces:
  - `require_candidate(db, candidate_id, owner_sub)`
  - `require_job(db, job_id, owner_sub)`
  - `list_candidates(db, owner_sub)`
  - `list_job_candidates(db, job_id, owner_sub, page, page_size)`
  - `assign_candidates(db, job_id, candidate_ids, owner_sub)`
  - `get_job_candidate_evaluation(db, job_id, candidate_id, owner_sub)`
  - `get_candidate_evaluations(db, candidate_id, owner_sub)`
  - `delete_candidate(db, candidate_id, owner_sub)`
  - `delete_all_candidates(db, owner_sub)`

- [ ] **Step 1: Write failing delegation/ownership tests**

Verify that `require_candidate` and `require_job` pass `owner_sub` into their repositories and raise domain exceptions when invisible. Verify `assign_candidates` validates the job before delegating and preserves `(assigned, skipped)`. Verify delete-by-id validates ownership before deleting.

- [ ] **Step 2: Run focused tests and verify RED for missing service functions**

```bash
python -m pytest app/tests/test_candidates_domain.py -v --tb=short
```

- [ ] **Step 3: Implement minimal service**

Imports:

```python
from app.domains.candidates import repository as candidates_repository
from app.domains.jobs import repository as jobs_repository
from app.domains.evaluations import repository as evaluations_repository
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound
```

Service functions must return domain objects/tuples and must not import FastAPI or presenter functions.

- [ ] **Step 4: Run focused tests and architecture tests**

```bash
python -m pytest app/tests/test_candidates_domain.py app/tests/test_architecture_boundaries.py -v --tb=short
```

Expected: PASS while Candidates router remains temporarily allow-listed.

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidates/service.py app/tests/test_candidates_domain.py
git commit -m "refactor: add candidates application service"
```

---

### Task 4: Move bulk upload/index orchestration behind the service

**Files:**
- Modify: `app/domains/candidates/service.py`
- Test: `app/tests/test_candidates_domain.py`

**Interfaces:**
- Produces: `create_and_index_candidate(db, *, owner_sub, original_filename, file_content) -> tuple[Candidate, dict]`.

- [ ] **Step 1: Write ordering and propagation tests**

Monkeypatch `candidates_repository.create_candidate` and `index_candidate_document`. Assert the event sequence is `create` then `index`, indexing receives the candidate returned by create, and the service returns the provider result unchanged.

```python
assert events == ["create", "index"]
assert indexing["status"] == "COMPLETE"
```

Also assert an indexing exception propagates so the router can preserve per-file catch behavior; do not delete or rollback the created candidate.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest app/tests/test_candidates_domain.py -v --tb=short
```

- [ ] **Step 3: Implement minimal orchestration**

The service derives the candidate name with `os.path.splitext(original_filename or "Unknown")[0]`, calls `create_candidate` with `metadata={"filename": original_filename}`, then calls `index_candidate_document(candidate, file_content, original_filename)`.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python -m pytest app/tests/test_candidates_domain.py -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidates/service.py app/tests/test_candidates_domain.py
git commit -m "refactor: move candidate indexing orchestration to service"
```

---

### Task 5: Migrate Candidates router and shrink architecture allow-list

**Files:**
- Modify: `app/domains/candidates/router.py`
- Modify: `app/tests/test_architecture_boundaries.py`
- Test: existing `app/tests/test_contract.py`, `app/tests/test_integrity_multitenant.py`, `app/tests/test_ranking.py`, `app/tests/test_candidates_domain.py`

**Interfaces:**
- Router consumes Candidates `service`, `presenter`, and domain exceptions plus `app.deps`/FastAPI types only.

- [ ] **Step 1: Make the architecture test demand the final boundary**

Remove exactly this entry from `CRUD_ROUTER_ALLOWLIST`:

```python
"domains/candidates/router.py",
```

Run:

```bash
python -m pytest app/tests/test_architecture_boundaries.py -v --tb=short
```

Expected: FAIL because Candidates router still imports `app.crud`.

- [ ] **Step 2: Replace router persistence/provider calls**

Remove:

```python
from app import crud
from app.infrastructure.storage.candidate_documents import index_candidate_document
```

Import:

```python
from app.domains.candidates import presenter, service
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound
```

Map `CandidateNotFound` and `JobNotFound` to the exact existing 404 details. Keep empty `candidate_ids` validation in the router. Keep per-file bulk upload exception capture and existing bulk response counts/keys.

- [ ] **Step 3: Remove duplicated response mapping from router**

Use presenter functions for candidate lists/details and evaluation/detail/explanation/requirements. No response key may change.

- [ ] **Step 4: Run focused regression**

```bash
python -m pytest \
  app/tests/test_candidates_domain.py \
  app/tests/test_architecture_boundaries.py \
  app/tests/test_contract.py \
  app/tests/test_integrity_multitenant.py \
  app/tests/test_ranking.py \
  -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidates/router.py app/tests/test_architecture_boundaries.py

git commit -m "refactor: migrate candidates router off crud facade"
```

---

### Task 6: Full verification and PR

**Files:**
- Verification only; update docs only if implementation differs materially from this plan.

- [ ] **Step 1: Run/require the full backend gate**

```bash
python -m pytest app/tests/ -v --tb=short
python -m pytest app/tests/test_contract.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 2: Require PostgreSQL smoke**

Use the repository CI job `Backend smoke (Postgres)` and require success.

- [ ] **Step 3: Require frontend regression gates**

Require frontend lint, tests, and production build success even though no frontend file should change.

- [ ] **Step 4: Review the diff against `main`**

Confirm there are no modifications under `alembic/`, model definitions, deployment files, or `frontend-react/`. Confirm `domains/candidates/router.py` contains neither `app.crud` nor direct storage/repository imports.

- [ ] **Step 5: Open/update the PR**

Use title:

```text
refactor: complete candidates domain boundary
```

PR body must state compatibility guarantees and exact test counts from the final CI run.
