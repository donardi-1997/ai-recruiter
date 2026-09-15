# Candidates Domain Completion Design

**Date:** 2026-09-11
**Status:** Approved incremental modular-monolith follow-on
**Repository:** `donardi-1997/ai-recruiter`
**Base:** `main` at `d8a79c34787e09a72653d78bbb557512edd8ea65`

## Purpose

Complete the Candidates backend domain boundary without changing its HTTP contract. The current `app/domains/candidates/router.py` is roughly 11.5 KB and mixes HTTP mapping, ownership checks, persistence calls through `app.crud`, evaluation presentation, file-upload orchestration, and document indexing.

This subproject migrates Candidates off the compatibility facade and makes its router a thin HTTP adapter.

## Goals

- Add `app/domains/candidates/service.py` for candidate use-case orchestration.
- Add `app/domains/candidates/presenter.py` for stable response mapping.
- Add `app/domains/candidates/exceptions.py` for domain errors mapped by the router.
- Remove `from app import crud` from the Candidates router.
- Remove `domains/candidates/router.py` from the architecture-test CRUD allow-list.
- Preserve tenant/owner isolation.
- Preserve file upload/indexing semantics and per-file error behavior.
- Preserve all existing candidate/job-candidate endpoints, payloads, status codes, and public failed-evaluation sanitization.

## Non-Goals

- No database migration or model change.
- No endpoint rename or response redesign.
- No Bedrock scoring/evaluation rewrite.
- No storage-provider rewrite.
- No Jobs-domain service extraction in this PR.
- No Evaluation/Ranking cross-domain redesign in this PR.
- No frontend changes.
- Do not delete `app/crud.py`; other domains still consume it.

## Target Structure

```text
app/domains/candidates/
  __init__.py
  exceptions.py   # CandidateNotFound, JobNotFound
  presenter.py    # candidate/evaluation/requirements response mapping
  repository.py   # candidate persistence only
  router.py       # FastAPI adapter only
  schemas.py
  service.py      # ownership, assignment, upload/index orchestration, evaluation reads
```

## Service Boundary

`service.py` may depend on:

- `app.domains.candidates.repository`;
- `app.domains.jobs.repository` temporarily for job ownership checks;
- `app.domains.evaluations.repository` temporarily for read-only evaluation lookup;
- `app.infrastructure.storage.candidate_documents.index_candidate_document` for document indexing.

The direct cross-domain repository dependencies are explicitly transitional and will be replaced in the Jobs and Evaluation/Ranking follow-on phases. They are preferable here to keeping orchestration in the HTTP router or compatibility facade.

The service must not import FastAPI types or raise `HTTPException`.

## Domain Errors

Use internal exceptions:

```python
class CandidateNotFound(Exception):
    pass

class JobNotFound(Exception):
    pass
```

The router maps these to the existing Spanish 404 responses:

- `CandidateNotFound` -> `404 Candidato no encontrado.`
- `JobNotFound` -> `404 Vacante no encontrada.`

Other existing HTTP validation remains in the router, including empty `candidate_ids` -> 400.

## Presenter Boundary

`presenter.py` owns pure mappings only. It does not access the database or external providers.

Required functions:

- `candidate_to_dict(candidate) -> dict`
- `evaluation_to_dict(evaluation) -> dict`
- `evaluation_explanation_to_dict(evaluation | None) -> dict`
- `evaluation_requirements_to_dict(evaluation | None) -> dict`

The existing failed-evaluation public string remains exactly:

`No fue posible completar la evaluación. Intenta nuevamente.`

The existing fallback from strengths/gaps to requirement entries remains unchanged.

## Upload Semantics

Bulk upload remains sequential per request and keeps current behavior:

1. filename becomes candidate name using `os.path.splitext`;
2. empty content yields a per-file `Empty file` error and creates no candidate;
3. candidate is persisted before document indexing;
4. indexing receives the persisted candidate, raw bytes, and original filename;
5. indexing result exposes existing `status`, `ingestion_job_id`, and `error` fields;
6. a provider/indexing exception is caught per file by the router and included in `errors`;
7. no rollback of the already-created candidate is introduced.

## Transaction Semantics

Repositories keep their existing commit behavior. This PR does not add a Unit of Work or change commit/rollback ownership.

## Architecture Guard

Once migration is complete, `domains/candidates/router.py` is removed from `CRUD_ROUTER_ALLOWLIST`. The guard must then fail if Candidates imports `app.crud` again.

## Testing

Add focused service/presenter tests before migration. Existing required gates remain:

- full backend pytest on SQLite;
- contract tests;
- PostgreSQL smoke;
- frontend lint/tests/build.

Characterize at minimum:

- owner-scoped candidate lookup and CandidateNotFound;
- owner-scoped job lookup and JobNotFound;
- assignment delegation and counts;
- list/get candidate presentation;
- failed evaluation sanitization;
- requirements fallback from strengths/gaps;
- upload create-before-index ordering and indexing result propagation;
- architecture guard rejects Candidates `app.crud` dependency after migration.

## Acceptance Criteria

1. `app/domains/candidates/router.py` has no `app.crud` import.
2. Router contains no direct repository or storage-provider calls.
3. Candidate ownership/job ownership remain enforced.
4. Candidate upload/index behavior is unchanged.
5. Public candidate/evaluation JSON contracts remain unchanged.
6. `domains/candidates/router.py` is removed from the CRUD allow-list.
7. No model/Alembic/frontend files change.
8. All required CI gates pass.
