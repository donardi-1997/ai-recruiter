# Jobs Application Boundary Design

**Date:** 2026-09-11
**Status:** Approved design direction; implementation not started
**Base:** `main` at `dc07f08ee8d66a841ae0a2c57807f4e758f0a6d1`

## Purpose

Remove the remaining `app.crud` dependency and business orchestration from the Jobs HTTP router while preserving all existing public behavior, multitenant guarantees, deletion semantics, and deployment characteristics.

## Current State

`app/domains/jobs/router.py` currently:
- imports and calls `app.crud` directly;
- performs owner-scoped job lookup in the HTTP layer;
- assembles public response payloads inline;
- calculates candidate counts inline for job listings;
- orchestrates update and delete behavior from the router.

`app/domains/jobs/repository.py` already owns the persistence logic for job CRUD and deletion cascades.

## Target Structure

```text
app/domains/jobs/
  router.py       # HTTP adapter only
  schemas.py      # existing request/response contracts
  service.py      # owner-scoped Jobs use cases
  presenter.py    # public payload construction
  exceptions.py   # Jobs domain/application errors
  repository.py   # persistence and transaction behavior
```

## Service Boundary

Add explicit application-service functions for Jobs use cases:

```python
def require_job(db, job_id: str, owner_sub: str): ...
def list_jobs(db, owner_sub: str): ...
def create_job(db, *, title: str, description: str | None, owner_sub: str): ...
def update_job(db, *, job_id: str, title: str | None, description: str | None, owner_sub: str): ...
def delete_job(db, *, job_id: str, owner_sub: str, delete_candidates: bool): ...
```

The service owns owner-scoped authorization and orchestration. It delegates persistence to `jobs.repository` and returns domain objects/result data without importing FastAPI types.

## Presenter Boundary

Move public payload construction out of the router. The presenter preserves the exact existing payload shapes, including:
- `job_id` and `id` aliases;
- ISO formatted `created_at`;
- `candidate_count` on list responses;
- delete response strings and counters.

Candidate counting remains repository-backed; the router does not call persistence directly.

## Error Contract

Introduce a Jobs-level `JobNotFound` exception. The router maps it to the existing public response:

- HTTP 404
- detail: `Vacante no encontrada.`

No provider, SQLAlchemy, or internal exception details are exposed.

## Deletion Semantics

The existing repository deletion behavior is preserved exactly in this phase:
- `delete_candidates=false` deletes the job and its links/evaluations/rankings but preserves candidates;
- `delete_candidates=true` deletes owner-visible assigned candidates and their dependent data;
- unassigned candidates are preserved;
- candidates owned by another tenant are preserved;
- shared candidates retain the existing documented behavior;
- transaction rollback behavior remains unchanged.

The repository implementation is not redesigned in this phase because its behavior is already covered by regression tests.

## Dependency Rules

After migration, `app/domains/jobs/router.py` may import only:
- FastAPI primitives;
- SQLAlchemy `Session` for request dependency typing;
- `app.deps` HTTP adapters;
- Jobs schemas, service, presenter, and Jobs exceptions.

It must not import:
- `app.crud`;
- any `*.repository` module;
- infrastructure providers;
- SQLAlchemy query/model code.

`domains/jobs/router.py` is removed from `CRUD_ROUTER_ALLOWLIST`.

## Compatibility Requirements

This is a behavior-preserving refactor. It intentionally changes none of the following:
- `/api/jobs` routes;
- request payloads;
- status codes;
- response payloads;
- database schema or Alembic history;
- Cognito behavior;
- candidate deletion semantics;
- evaluation/ranking behavior;
- frontend behavior or ASIATI branding;
- deployment topology or environment variables.

## TDD Strategy

Before implementation:
1. add focused service tests for owner scoping and repository delegation;
2. add presenter tests for the exact public Jobs payloads;
3. remove Jobs from the architecture allow-list and add a Jobs router dependency guard;
4. confirm the intended RED failures.

Then implement the minimum service/presenter/router changes required to make the new tests green.

## Verification Gates

Required before merge:
- focused Jobs domain tests;
- full backend pytest;
- existing Jobs deletion/multitenancy suite;
- 20 contract tests;
- PostgreSQL smoke;
- frontend lint, tests, and production build;
- architecture guards;
- diff review confirming no model, Alembic, frontend, branding, or deployment changes.

## Acceptance Criteria

1. Jobs router contains no `app.crud` import.
2. Jobs router contains no repository or infrastructure imports.
3. Owner scoping remains identical for list/update/delete operations.
4. Existing 404 detail remains exactly `Vacante no encontrada.`.
5. Existing list/create/update/delete response payloads remain unchanged.
6. Existing deletion and rollback semantics remain unchanged.
7. Jobs is removed from the transitional `app.crud` router allow-list.
8. Architecture tests prevent regression of the Jobs HTTP boundary.
9. No database schema, frontend, branding, or deployment changes occur.
10. All verification gates pass before merge.
