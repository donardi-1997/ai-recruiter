# Indeed Employers Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated, production-safe Indeed Employers Job Sync integration to the existing AI Recruiter backend.

**Architecture:** Extend the neutral Job model with publication metadata, add a dedicated `app/domains/indeed` adapter around Indeed OAuth/GraphQL, persist provider links/events separately, and expose explicit authenticated publish/status/expire endpoints. The integration remains disabled by default and is testable without network access.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, httpx, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-indeed-integration-design.md`

## Global Constraints

- Work only on `feat/indeed-integration-foundation`; never commit feature code directly to `main`.
- `INDEED_ENABLED=false` by default.
- No live Indeed requests in CI/tests.
- Never log client secrets or bearer tokens.
- Core Candidate and Job models must not store Indeed IDs/enums.
- Failed external operations must not delete or roll back local jobs.

---

### Task 1: Add neutral job publication fields

**Files:**
- Modify: `app/models.py`
- Modify: `app/domains/jobs/schemas.py`
- Modify: `app/domains/jobs/repository.py`
- Modify: `app/domains/jobs/service.py`
- Modify: `app/domains/jobs/router.py`
- Modify: `app/domains/jobs/presenter.py`
- Create: `app/migrations/versions/004_indeed_job_sync.py`
- Test: `app/tests/test_indeed_integration.py`

**Interfaces:**
- Produces Job fields `country_code`, `city`, `employment_type`, `public_slug`, `published_at`.

- [ ] Write tests asserting create/update/presentation preserve neutral publication fields.
- [ ] Verify tests fail because fields do not exist.
- [ ] Add ORM columns, request/response schema fields, repository/service/router propagation, and migration.
- [ ] Verify targeted tests pass.

### Task 2: Add Indeed configuration and mapper

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `app/domains/indeed/__init__.py`
- Create: `app/domains/indeed/constants.py`
- Create: `app/domains/indeed/exceptions.py`
- Create: `app/domains/indeed/mapper.py`
- Test: `app/tests/test_indeed_integration.py`

**Interfaces:**
- Produces `IndeedSettings`, `get_indeed_settings()`, `build_job_payload(job, careers_base_url)`.

- [ ] Write mapper/config tests for disabled defaults, required-field validation, URL building, and employment-type mapping.
- [ ] Verify RED.
- [ ] Implement minimal config/mapper.
- [ ] Verify GREEN.

### Task 3: Add OAuth/GraphQL client

**Files:**
- Create: `app/domains/indeed/client.py`
- Test: `app/tests/test_indeed_integration.py`

**Interfaces:**
- Produces `IndeedClient.execute(query, variables)` and in-memory token cache.

- [ ] Write tests for token acquisition, caching, bearer header, HTTP failure, and top-level GraphQL errors using `httpx.MockTransport`.
- [ ] Verify RED.
- [ ] Implement client with injected `httpx.Client` support.
- [ ] Verify GREEN.

### Task 4: Add Indeed persistence and service

**Files:**
- Modify: `app/models.py`
- Create: `app/domains/indeed/repository.py`
- Create: `app/domains/indeed/service.py`
- Create: `app/domains/indeed/schemas.py`
- Test: `app/tests/test_indeed_integration.py`

**Interfaces:**
- Produces `publish_job`, `get_job_status`, `expire_job`, persisted `IndeedConnection`, `IndeedJobLink`, `IndeedSyncEvent`.

- [ ] Write service tests with fake client for publish/status/expire, ownership, missing link, disabled config, and failed event persistence.
- [ ] Verify RED.
- [ ] Implement repositories and service orchestration.
- [ ] Verify GREEN.

### Task 5: Expose routes and register integration

**Files:**
- Create: `app/domains/indeed/router.py`
- Modify: `app/bootstrap.py`
- Test: `app/tests/test_indeed_integration.py`

**Interfaces:**
- `GET /api/integrations/indeed/status`
- `POST /api/jobs/{job_id}/integrations/indeed/publish`
- `GET /api/jobs/{job_id}/integrations/indeed/status`
- `POST /api/jobs/{job_id}/integrations/indeed/expire`

- [ ] Write router tests for success and 404/422/502/503 mappings.
- [ ] Verify RED.
- [ ] Implement router and bootstrap registration.
- [ ] Verify GREEN.

### Task 6: CI verification and PR

- [ ] Run the full backend suite through GitHub Actions.
- [ ] Inspect failures and fix feature regressions only.
- [ ] Re-run until CI is green.
- [ ] Open a PR from `feat/indeed-integration-foundation` to `main` with scope, security notes, and activation instructions.
