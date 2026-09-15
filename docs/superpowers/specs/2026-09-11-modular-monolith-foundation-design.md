# Modular Monolith Foundation Design

**Date:** 2026-09-11  
**Status:** Approved design direction; implementation not started  
**Repository:** `donardi-1997/ai-recruiter`  
**Target branch:** `main`

## 1. Purpose

AI Recruiter will remain a single deployable FastAPI + React application while adopting stricter module boundaries. The goal is to make the system easier to change, test, and operate without introducing distributed-system complexity.

This document defines the first architectural subproject in the incremental modular-monolith route: **foundation and dependency boundaries**. It establishes the rules and shared infrastructure required before refactoring individual domains and large frontend features.

## 2. Current State

The codebase already contains a partial domain split:

- `app/domains/jobs`
- `app/domains/candidates`
- `app/domains/evaluations`
- `app/domains/ranking`
- `app/infrastructure/bedrock`
- `app/infrastructure/storage`

However, important boundaries are still porous:

1. `app/crud.py` remains a compatibility facade and some routers still depend on it.
2. `app/deps.py` mixes unrelated responsibilities: database sessions, PostgreSQL advisory locking, and Cognito authentication.
3. `ranking.service` imports repositories from several domains directly and also imports lock helpers from `app.deps`.
4. HTTP routers still contain orchestration and presentation logic that belongs in services/presenters.
5. The React frontend still has page components such as `Candidates.jsx` and `Ranking.jsx` that combine API calls, state machines, upload behavior, modals, and rendering.

The first phase will address the backend foundation only. Frontend feature decomposition is intentionally a later subproject.

## 3. Architectural Decision

Use an **incremental modular monolith**.

The application remains one process and one deployment unit. Modules communicate through explicit Python APIs instead of network calls. Database transactions can remain local and atomic. Existing infrastructure, endpoints, persistence, Cognito authentication, Bedrock evaluation, and deployment topology remain unchanged.

### Why not microservices

Microservices would add network failure modes, distributed tracing, service discovery, separate deployment pipelines, cross-service data consistency, and more operational overhead. The current product does not need those trade-offs to obtain modularity.

### Why not a full ports-and-adapters rewrite

A complete clean-architecture rewrite would create too much abstraction at once and increase migration risk. Interfaces will be introduced only where they create a real boundary: external infrastructure, cross-domain orchestration, and reusable application services.

## 4. Goals

This foundation phase must:

- Reduce `app.deps` to FastAPI dependency adapters only.
- Move Cognito-specific logic into infrastructure.
- Move PostgreSQL advisory locking into infrastructure.
- Introduce a small application factory/composition root.
- Define and enforce dependency-direction rules.
- Preserve all public HTTP contracts and behavior.
- Preserve PostgreSQL and SQLite test behavior.
- Preserve Cognito authentication semantics.
- Preserve ranking concurrency semantics.
- Establish tests that make future domain extraction safer.

## 5. Non-Goals

This phase will not:

- Change any API route, request payload, response payload, or status code intentionally.
- Change database schemas or Alembic migrations.
- Change Cognito configuration or token format.
- Change Bedrock prompts, retrieval, evaluation scoring, or ranking behavior.
- Change S3/storage semantics.
- Split the application into services.
- Rewrite repositories into generic repository abstractions.
- Decompose `Candidates.jsx` or `Ranking.jsx` yet.
- Remove `app/crud.py` in one step; removal happens after all consumers migrate.

## 6. Backend Target Structure

The backend should converge toward this structure:

```text
app/
  main.py                     # ASGI entry point only
  bootstrap.py                # create_app(), router wiring, middleware, handlers
  config.py                   # application settings/environment access
  db.py                       # SQLAlchemy engine/session/base
  deps.py                     # FastAPI adapters: get_db, get_current_user

  infrastructure/
    auth/
      __init__.py
      cognito.py              # Cognito client + token/user validation
    locking/
      __init__.py
      job_lock.py             # advisory lock implementation
    bedrock/
      ...
    storage/
      ...

  domains/
    jobs/
      router.py
      schemas.py
      service.py
      repository.py
    candidates/
      router.py
      schemas.py
      service.py
      repository.py
    evaluations/
      router.py
      schemas.py
      service.py
      repository.py
      presenter.py
      rules.py
    ranking/
      router.py
      schemas.py
      service.py
      repository.py
      exceptions.py
```

Not every domain needs all four layers immediately. Files are added when responsibility actually exists.

## 7. Dependency Rules

These rules are mandatory for new and migrated code.

### 7.1 Router rules

A domain router may depend on:

- its own schemas;
- its own application service;
- `app.deps` for FastAPI dependency adapters;
- FastAPI types.

A router must not directly depend on:

- another domain's repository;
- SQLAlchemy queries;
- boto3 clients;
- Bedrock clients;
- advisory-lock SQL;
- `app.crud` after that route has been migrated.

### 7.2 Service rules

A domain service owns business orchestration and transaction-level behavior for its use cases.

A service may depend on:

- its own repository;
- explicit public services from another domain when cross-domain orchestration is required;
- infrastructure capabilities with stable interfaces where necessary.

A service must not depend on FastAPI request/response objects or HTTP exceptions.

### 7.3 Repository rules

A repository owns persistence queries for one domain. It may depend on SQLAlchemy models and the database session.

A repository must not:

- call external services;
- raise HTTP exceptions;
- orchestrate other domains;
- import routers.

### 7.4 Infrastructure rules

Infrastructure contains provider-specific and platform-specific code such as:

- Cognito;
- Bedrock;
- S3/document storage;
- PostgreSQL advisory locks.

Infrastructure modules must not import HTTP routers or presentation code.

### 7.5 Cross-domain rule

Cross-domain behavior must be explicit at the service boundary. A domain service should not reach into another domain's private persistence details when a public application service can express the operation.

During migration, direct repository imports may remain temporarily when behavior-preserving extraction would otherwise be too large. Each temporary dependency must be removed in a later domain-specific phase.

## 8. Composition Root

`app/main.py` should become a thin ASGI entry point:

```python
from app.bootstrap import create_app

app = create_app()
```

`app/bootstrap.py` will own:

- FastAPI construction;
- application metadata;
- CORS middleware registration;
- router registration;
- global exception-handler registration;
- startup/lifespan registration.

This makes application construction testable without importing deployment-specific side effects through a large module.

## 9. Configuration Boundary

Environment access should stop spreading through runtime modules.

`app/config.py` will expose a small settings object or functions for stable application configuration, including at minimum:

- AWS region;
- allowed CORS origins;
- database URL only where needed for startup decisions.

This phase will not introduce a heavy settings framework unless the existing dependencies already justify it. Standard-library/environment-based configuration is acceptable.

## 10. Authentication Boundary

### Current problem

`app.deps.py` creates and caches the boto3 Cognito client and performs token validation directly.

### Target

`app/infrastructure/auth/cognito.py` owns:

- Cognito client construction/caching;
- access-token validation;
- normalization to the existing user shape: `{"sub": ..., "email": ...}`;
- provider-error handling at the infrastructure boundary.

`app.deps.get_current_user()` remains the HTTP adapter. It reads the Bearer token, delegates validation to the Cognito infrastructure module, and maps authentication failures to the existing HTTP 401 contract.

The public authentication behavior must remain identical.

## 11. Locking Boundary

### Current problem

PostgreSQL advisory-lock implementation lives inside `app.deps.py`, even though it is infrastructure rather than a FastAPI dependency.

### Target

`app/infrastructure/locking/job_lock.py` owns:

- deterministic lock-key generation;
- PostgreSQL `pg_try_advisory_lock`;
- PostgreSQL `pg_advisory_unlock`;
- SQLite no-op behavior used by tests.

The ranking service imports locking from this infrastructure module, not from `app.deps`.

Concurrency behavior must remain exactly the same.

## 12. Compatibility Facade Strategy

`app/crud.py` is already documented as a compatibility facade. It will remain temporarily, but new code must not import from it.

Migration policy:

1. Move one consumer at a time to its domain repository/service.
2. Run contract and domain tests after each migration.
3. Remove re-exports only when no runtime or test consumer needs them.
4. Delete `app/crud.py` only in a later phase after repository-wide search confirms zero imports.

This prevents a high-risk all-at-once migration.

## 13. Error Handling

Domain/application services should use domain exceptions or result objects where appropriate. HTTP mapping belongs in routers or central exception handlers.

This foundation phase will not redesign all error types. It will preserve current externally visible errors and only introduce internal exception types when required to move provider-specific logic out of adapters.

No raw Cognito, boto3, SQL, or Bedrock error should become newly exposed to API clients.

## 14. Transaction and Session Semantics

The existing SQLAlchemy session lifecycle remains request-scoped through `get_db`.

This phase will not add a Unit of Work abstraction. Existing repositories/services continue to receive a `Session` explicitly. This keeps transactions visible and avoids unnecessary abstraction.

A Unit of Work may be reconsidered only if future multi-step use cases require consistent commit/rollback ownership that cannot be expressed clearly with the current session pattern.

## 15. Testing Strategy

### 15.1 Characterization first

Before moving authentication or locking code, tests must characterize their current contracts.

Required tests:

- missing Authorization header -> existing 401 contract;
- invalid/expired Cognito token -> existing 401 contract;
- normalized Cognito user keeps `sub` and `email` behavior;
- advisory-lock key is deterministic;
- SQLite lock acquire returns `True` and release is a no-op;
- PostgreSQL locking behavior remains covered by the existing smoke suite;
- application factory registers the same critical routes.

### 15.2 Existing gates remain mandatory

The following must pass before merge:

- Python syntax validation;
- backend pytest suite on SQLite;
- backend contract tests;
- PostgreSQL smoke tests;
- frontend lint;
- frontend tests;
- frontend production build.

Even though this phase is backend-focused, frontend CI remains a required regression gate.

## 16. Migration Sequence

### Phase F1 — Foundation safety tests

Add characterization tests for auth, locking, and application construction before moving implementation.

### Phase F2 — Locking extraction

Create `app/infrastructure/locking/job_lock.py`, move the existing implementation, keep behavior unchanged, and update ranking imports.

### Phase F3 — Authentication extraction

Create `app/infrastructure/auth/cognito.py`, move Cognito client/token logic, and reduce `get_current_user` to an HTTP adapter.

### Phase F4 — Application bootstrap

Create `app/bootstrap.py`, move FastAPI construction/wiring from `app/main.py`, and keep `app.main:app` as the deployment entry point.

### Phase F5 — Configuration cleanup

Centralize stable environment-derived settings needed by bootstrap/auth without changing deployment environment variable names.

### Phase F6 — Dependency guard tests

Add lightweight architecture tests that reject new imports from prohibited layers, especially:

- routers importing `app.crud`;
- domains importing from routers;
- infrastructure importing domain routers;
- non-adapter code importing locking from `app.deps`.

Existing transitional `app.crud` consumers may be allow-listed explicitly until their domain phase removes them. The allow-list must only shrink.

## 17. Follow-On Subprojects

These are separate design/implementation cycles, not part of this foundation PR series:

1. **Candidates domain completion** — service extraction, direct repository usage, upload/index orchestration, assignment flows.
2. **Evaluation/ranking boundaries** — make ranking consume explicit application services instead of private repository details where practical.
3. **Jobs/auth cleanup** — complete service boundaries and remove remaining compatibility imports.
4. **Compatibility facade removal** — delete `app/crud.py` once usage reaches zero.
5. **Frontend feature architecture** — split `Candidates.jsx` and `Ranking.jsx` into `features/*`, API modules, hooks, and focused components.
6. **Shared frontend layer** — stabilize `shared/api`, `shared/ui`, and cross-feature utilities while preserving the ASIATI design system.

Each subproject receives its own focused spec and implementation plan.

## 18. Rollback Strategy

Every implementation PR in this route must be behavior-preserving and independently revertible.

Rollback principles:

- no schema migration in foundation work;
- no API contract change;
- no environment-variable rename;
- no deployment-topology change;
- one architectural concern per PR where practical;
- retain compatibility facades until consumers are migrated.

If a production regression occurs, revert the latest architecture PR without requiring data rollback.

## 19. Acceptance Criteria

The foundation subproject is complete when all of the following are true:

1. `app/main.py` is a thin composition entry point.
2. FastAPI construction and router/middleware/error/startup wiring live in `app/bootstrap.py`.
3. Cognito provider logic is outside `app/deps.py` under infrastructure.
4. PostgreSQL advisory-lock logic is outside `app/deps.py` under infrastructure.
5. Ranking no longer imports lock helpers from `app.deps`.
6. `app/deps.py` contains only request/dependency adapters and database-session lifecycle concerns.
7. Existing public API behavior remains unchanged.
8. No database migration is required.
9. SQLite tests, contract tests, PostgreSQL smoke tests, frontend tests, lint, and build all pass.
10. Architecture guard tests prevent new dependency violations while allowing only explicitly documented transitional exceptions.
11. The ASIATI branding merged before this work remains unchanged.

## 20. Success Metric

The immediate success metric is not line-count reduction. It is **dependency clarity**: infrastructure concerns have explicit homes, the application has a clean composition root, and future domain refactors can proceed without using `app.deps` or `app.crud` as global coupling points.
