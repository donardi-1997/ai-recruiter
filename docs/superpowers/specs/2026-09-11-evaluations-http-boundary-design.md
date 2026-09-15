# Evaluations HTTP Boundary Design

**Date:** 2026-09-11
**Status:** Approved modular-monolith follow-on
**Base:** `main` at `2bfcdd36ce34115d437496cfda85e1ac77ad0b2a`

## Purpose

Remove the remaining `app.crud` dependency from the Evaluations HTTP router while preserving the existing evaluation engine and public API contract.

## Current State

`app/domains/evaluations/router.py` uses `app.crud` only to load and authorize the candidate and job, then calls `evaluate_candidate_for_job(...)`. The domain already has `service.py`, `repository.py`, `presenter.py`, `rules.py`, and schemas.

## Target

- Keep `evaluate_candidate_for_job(db, candidate, job)` unchanged as the object-based orchestration API used by Ranking.
- Add an owner-scoped service entrypoint for HTTP requests.
- Move candidate/job lookup and authorization out of the router.
- Remove `domains/evaluations/router.py` from the `app.crud` transition allow-list.
- Add a router boundary guard preventing repositories or `app.crud` from being imported directly.

## Service API

Add:

```python
def evaluate_candidate_for_owner(
    db,
    *,
    candidate_id: str,
    job_id: str,
    owner_sub: str,
):
    ...
```

The function:
1. resolves the candidate with owner scoping;
2. resolves the job with owner scoping;
3. raises domain-level not-found errors rather than `HTTPException`;
4. delegates unchanged scoring/persistence to `evaluate_candidate_for_job`;
5. returns the same `(evaluation, newly_evaluated, internal_error)` tuple.

## Dependencies

The Evaluations service may depend on:
- `app.domains.candidates.service` as the public Candidates use-case boundary;
- `app.domains.jobs.repository` temporarily until Jobs gets its own application-service boundary;
- its existing Evaluations repository/rules.

No FastAPI types are allowed in the service.

## Errors

Candidate visibility failures continue to surface as `404 Candidato no encontrado.`.
Job visibility failures continue to surface as `404 Vacante no encontrada.`.

The router maps domain exceptions to those exact existing responses.

## Non-Goals

- No change to Bedrock retrieval or LLM prompts.
- No scoring/rule changes.
- No evaluation persistence changes.
- No Ranking orchestration changes.
- No schema/model/Alembic changes.
- No frontend changes.

## Architecture Guard

After migration:
- `domains/evaluations/router.py` is removed from `CRUD_ROUTER_ALLOWLIST`;
- the router must not import `app.crud`, any `*.repository`, or infrastructure providers directly.

## Verification

Required gates:
- focused service tests for owner-scoped candidate/job authorization and delegation;
- existing evaluation contract tests, including public error sanitization and summary-length validation;
- full backend pytest;
- contract suite;
- PostgreSQL smoke;
- frontend lint/tests/build.

## Acceptance Criteria

1. Evaluations router contains no `app.crud` import.
2. Evaluations router contains no repository/infrastructure imports.
3. `evaluate_candidate_for_job` behavior and signature remain intact.
4. Candidate/job ownership behavior and 404 strings remain intact.
5. Public evaluation payload is unchanged.
6. No database/frontend/deployment behavior changes.
7. All CI gates pass.
