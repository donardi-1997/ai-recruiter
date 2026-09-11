# Jobs Application Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `app.crud` and orchestration from the Jobs HTTP router while preserving all existing Jobs API and deletion behavior.

**Architecture:** Introduce a Jobs application service for owner-scoped use cases, a presenter for public payload construction, and a Jobs exception for missing/invisible jobs. Keep persistence and transaction behavior in the existing Jobs repository. The router becomes an HTTP-only adapter.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-jobs-application-boundary-design.md`

## Global Constraints

- Preserve `/api/jobs` routes, request bodies, status codes, and response payloads exactly.
- Preserve exact 404 detail: `Vacante no encontrada.`
- Preserve current deletion semantics and rollback behavior.
- Do not change models, Alembic, Cognito, frontend, ASIATI branding, or deployment configuration.
- Use TDD: observe RED before production implementation.

---

### Task 1: Jobs service and presenter contract

**Files:**
- Create: `app/tests/test_jobs_domain.py`
- Create: `app/domains/jobs/exceptions.py`
- Create: `app/domains/jobs/service.py`
- Create: `app/domains/jobs/presenter.py`

**Interfaces:**
- Produces: `JobNotFound`
- Produces: `require_job(db, job_id, owner_sub)`
- Produces: `list_jobs(db, owner_sub)` returning `(job, candidate_count)` tuples
- Produces: `create_job(db, *, title, description, owner_sub)`
- Produces: `update_job(db, *, job_id, title, description, owner_sub)`
- Produces: `delete_job(db, *, job_id, owner_sub, delete_candidates)` returning deleted count
- Produces: `job_payload(job, candidate_count=None)` and `delete_job_payload(job_id, delete_candidates, deleted_candidates)`

- [ ] **Step 1: Write focused failing service/presenter tests**

Cover owner-scoped lookup, missing-job domain error, list candidate counts, update/delete delegation, and exact public payloads.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest app/tests/test_jobs_domain.py -v --tb=short`
Expected: FAIL because Jobs service/presenter boundaries do not exist.

- [ ] **Step 3: Implement minimal Jobs exception/service/presenter**

Use only `app.domains.jobs.repository` from the service. Do not import FastAPI in service/presenter.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m pytest app/tests/test_jobs_domain.py -v --tb=short`
Expected: all focused tests PASS.

- [ ] **Step 5: Commit**

Commit message: `refactor: add jobs application service boundary`

---

### Task 2: Enforce and migrate the Jobs HTTP boundary

**Files:**
- Modify: `app/tests/test_architecture_boundaries.py`
- Modify: `app/domains/jobs/router.py`

**Interfaces:**
- Consumes: Jobs service, presenter, and `JobNotFound` from Task 1.
- Produces: an HTTP-only Jobs router with no `app.crud`, repository, infrastructure, or model imports.

- [ ] **Step 1: Remove Jobs from `CRUD_ROUTER_ALLOWLIST` and add a Jobs router boundary test**

Guard must assert no `app.crud`, no `*.repository`, and no `app.infrastructure*` imports in `domains/jobs/router.py`.

- [ ] **Step 2: Run architecture tests to verify RED**

Run: `python -m pytest app/tests/test_architecture_boundaries.py -v --tb=short`
Expected: FAIL because the legacy Jobs router still imports `app.crud`.

- [ ] **Step 3: Migrate Jobs router to service/presenter**

Map `JobNotFound` to HTTP 404 with exact detail `Vacante no encontrada.`. Preserve list/create/update/delete responses and status codes.

- [ ] **Step 4: Run architecture and Jobs tests to verify GREEN**

Run: `python -m pytest app/tests/test_architecture_boundaries.py app/tests/test_jobs_domain.py app/tests/test_jobs.py -v --tb=short`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

Commit message: `refactor: isolate jobs HTTP boundary`

---

### Task 3: Full verification and merge gate

**Files:**
- No production changes unless verification finds a regression.

- [ ] **Step 1: Run full backend test suite**

Run: `python -m pytest app/tests/ -v --tb=short`
Expected: zero failures.

- [ ] **Step 2: Run contract tests**

Run: `python -m pytest app/tests/test_contract.py -v --tb=short`
Expected: 20 passed.

- [ ] **Step 3: Run PostgreSQL smoke through CI**

Expected: success.

- [ ] **Step 4: Run frontend lint/tests/build through CI**

Expected: success.

- [ ] **Step 5: Review branch diff against `main`**

Confirm no models, Alembic, frontend, branding, or deployment files changed.

- [ ] **Step 6: Mark PR ready and squash-merge only after all gates are green**
