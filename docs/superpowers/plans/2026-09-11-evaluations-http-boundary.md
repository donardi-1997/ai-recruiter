# Evaluations HTTP Boundary Implementation Plan

**Goal:** Remove `app.crud` and authorization orchestration from the Evaluations router without changing scoring or public behavior.

**Spec:** `docs/superpowers/specs/2026-09-11-evaluations-http-boundary-design.md`

### Task 1 — Characterize owner-scoped service entrypoint

- Add `app/tests/test_evaluations_domain.py`.
- Tests must require a new `evaluate_candidate_for_owner(...)` entrypoint.
- Verify candidate lookup is owner-scoped.
- Verify job lookup is owner-scoped.
- Verify missing candidate/job raise domain errors.
- Verify successful authorization delegates to existing `evaluate_candidate_for_job` with the resolved objects.
- Run focused tests and confirm RED before implementation.

### Task 2 — Implement owner-scoped service boundary

- Add only the minimal authorization/delegation code to `app/domains/evaluations/service.py`.
- Reuse Candidates service for candidate resolution.
- Temporarily use Jobs repository for owner-scoped job resolution.
- Keep `evaluate_candidate_for_job` unchanged.
- Run focused tests and existing evaluation contracts.

### Task 3 — Migrate router and enforce architecture

- Remove `domains/evaluations/router.py` from `CRUD_ROUTER_ALLOWLIST` first and confirm RED.
- Replace `app.crud` authorization helpers in the router with `evaluate_candidate_for_owner`.
- Preserve exact 404 details.
- Add an AST guard that Evaluations router imports neither `app.crud`, repositories, nor infrastructure providers.
- Run focused tests and contract tests.

### Task 4 — Full verification and merge

- Require full backend pytest.
- Require 20 contract tests.
- Require PostgreSQL smoke.
- Require frontend lint/tests/build.
- Confirm diff has no model/Alembic/frontend/deployment changes.
- Update PR with exact test counts.
- Squash merge only with verified head SHA.
