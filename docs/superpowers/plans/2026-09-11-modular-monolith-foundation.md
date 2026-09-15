# Modular Monolith Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish explicit backend composition, authentication, locking, configuration, and dependency boundaries without changing public API behavior, database schema, Cognito semantics, ranking concurrency, deployment topology, or ASIATI frontend branding.

**Architecture:** Keep AI Recruiter as one FastAPI + React deployable and refactor only the backend foundation. Provider/platform code moves under `app/infrastructure`, FastAPI wiring moves to a small `create_app()` composition root, and `app.deps` becomes an adapter layer. Existing domain behavior remains intact; `app.crud` is preserved temporarily and guarded by an explicit shrinking allow-list.

**Tech Stack:** Python, FastAPI, SQLAlchemy, boto3/Cognito, PostgreSQL advisory locks, SQLite test database, pytest, React 19, Vite, Vitest, ESLint.

**Spec:** `docs/superpowers/specs/2026-09-11-modular-monolith-foundation-design.md`

## Global Constraints

- Keep a single FastAPI + React deployment unit; do not introduce microservices.
- Do not intentionally change any API route, request payload, response payload, or HTTP status code.
- Do not add or modify database schemas or Alembic migrations.
- Do not rename Cognito, AWS, database, or deployment environment variables.
- Do not change Bedrock prompts, retrieval, evaluation scoring, ranking behavior, S3/storage semantics, or ranking concurrency semantics.
- Keep request-scoped SQLAlchemy sessions through `get_db`; do not introduce a Unit of Work abstraction.
- `app/crud.py` remains a compatibility facade during this plan; no new runtime imports from it are allowed.
- The ASIATI branding already merged into `main` must remain unchanged.
- Each implementation task must preserve a green backend suite and must not weaken PostgreSQL smoke coverage.

---

## File Structure

### Files created by this plan

- `app/infrastructure/locking/__init__.py` — locking package public surface.
- `app/infrastructure/locking/job_lock.py` — deterministic job lock key plus PostgreSQL/SQLite lock implementation.
- `app/infrastructure/auth/__init__.py` — authentication infrastructure package public surface.
- `app/infrastructure/auth/cognito.py` — Cognito client construction, token validation, normalized user identity, provider-level auth exception.
- `app/bootstrap.py` — FastAPI application factory, middleware, router registration, exception handling, startup registration.
- `app/config.py` — stable environment-derived settings and CORS origin constants.
- `app/tests/test_auth_dependency.py` — auth adapter/provider characterization tests.
- `app/tests/test_locking.py` — lock-key, SQLite, and SQL statement behavior tests.
- `app/tests/test_bootstrap.py` — application-factory and route-registration tests.
- `app/tests/test_architecture_boundaries.py` — AST-based dependency guard tests with a shrinking transitional allow-list.

### Files modified by this plan

- `app/deps.py` — retain `get_db` and HTTP auth adapter only; delegate Cognito validation to infrastructure.
- `app/domains/ranking/service.py` — import job locking from infrastructure instead of `app.deps`.
- `app/main.py` — reduce to `from app.bootstrap import create_app` and `app = create_app()`.
- `app/tests/test_contract.py` — move advisory-lock contract imports from `app.deps` to locking infrastructure after extraction.

### Files intentionally not modified

- `app/crud.py` — preserved until domain-specific migration plans.
- Domain router/service/repository behavior outside the single ranking lock import.
- `frontend-react/**` — no frontend architecture change in this foundation plan.

---

### Task 1: Add Foundation Characterization Tests

**Files:**
- Create: `app/tests/test_auth_dependency.py`
- Create: `app/tests/test_locking.py`
- Create: `app/tests/test_bootstrap.py`
- Existing reference: `app/deps.py`
- Existing reference: `app/main.py`

**Interfaces:**
- Consumes: current `app.deps.get_current_user`, `_get_cognito_client`, `_advisory_lock_key`, `acquire_job_lock`, `release_job_lock`, and `app.main.app`.
- Produces: behavior contracts that all later tasks must keep green.

- [ ] **Step 1: Add authentication characterization tests against the current adapter**

Create `app/tests/test_auth_dependency.py` with tests that construct a Starlette/FastAPI `Request` directly and monkeypatch the current Cognito client factory:

```python
import pytest
from fastapi import HTTPException, Request

import app.deps as deps


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_missing_authorization_header_keeps_401_contract():
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(_request())
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "No token provided."


def test_valid_cognito_user_normalizes_sub_and_email(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            assert AccessToken == "token-123"
            return {
                "Username": "legacy-user",
                "UserAttributes": [
                    {"Name": "sub", "Value": "stable-sub"},
                    {"Name": "email", "Value": "person@example.com"},
                ],
            }

    monkeypatch.setattr(deps, "_get_cognito_client", lambda: FakeCognito())
    user = deps.get_current_user(_request("Bearer token-123"))
    assert user == {"sub": "stable-sub", "email": "person@example.com"}


def test_invalid_cognito_token_keeps_401_contract(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            raise RuntimeError("provider rejected token")

    monkeypatch.setattr(deps, "_get_cognito_client", lambda: FakeCognito())
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(_request("Bearer bad-token"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token invalido o expirado."
```

- [ ] **Step 2: Add advisory-lock characterization tests against the current implementation**

Create `app/tests/test_locking.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.deps import _advisory_lock_key, acquire_job_lock, release_job_lock


def test_lock_key_is_deterministic_and_signed_64_bit():
    key = _advisory_lock_key("job-123")
    assert key == _advisory_lock_key("job-123")
    assert -(2**63) <= key < 2**63


def test_lock_key_changes_between_jobs():
    assert _advisory_lock_key("job-a") != _advisory_lock_key("job-b")


def test_sqlite_lock_acquire_is_true_and_release_is_noop():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        assert acquire_job_lock(db, "job-123") is True
        assert release_job_lock(db, "job-123") is None
```

- [ ] **Step 3: Add application-construction characterization test**

Create `app/tests/test_bootstrap.py`:

```python
from app.main import app


def test_current_app_exposes_critical_routes():
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/jobs" in paths
    assert "/api/candidates" in paths
    assert "/api/jobs/{job_id}/ranking" in paths
    assert "/api/jobs/{job_id}/ranking/recalculate" in paths
```

If `/health` differs in the current router, inspect `app/health.py` and use its exact current public path; do not rename the route.

- [ ] **Step 4: Run characterization tests before moving implementation**

Run:

```bash
python -m pytest app/tests/test_auth_dependency.py app/tests/test_locking.py app/tests/test_bootstrap.py -v
```

Expected: all newly added tests pass against the pre-refactor implementation. If one exposes a mismatch in the exact current contract, adjust the test to the current public behavior before refactoring rather than changing production behavior in this task.

- [ ] **Step 5: Run the existing backend contract baseline**

Run:

```bash
python -m pytest app/tests/test_contract.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the characterization safety net**

```bash
git add app/tests/test_auth_dependency.py app/tests/test_locking.py app/tests/test_bootstrap.py
git commit -m "test: characterize foundation architecture contracts"
```

---

### Task 2: Extract PostgreSQL Advisory Locking to Infrastructure

**Files:**
- Create: `app/infrastructure/locking/__init__.py`
- Create: `app/infrastructure/locking/job_lock.py`
- Modify: `app/deps.py`
- Modify: `app/domains/ranking/service.py`
- Modify: `app/tests/test_locking.py`
- Modify: `app/tests/test_contract.py`

**Interfaces:**
- Consumes: `sqlalchemy.orm.Session` and an existing session bind URL.
- Produces:
  - `app.infrastructure.locking.job_lock.advisory_lock_key(job_id: str) -> int`
  - `app.infrastructure.locking.job_lock.acquire_job_lock(db: Session, job_id: str) -> bool`
  - `app.infrastructure.locking.job_lock.release_job_lock(db: Session, job_id: str) -> None`

- [ ] **Step 1: Point lock tests at the target infrastructure interface before it exists**

Replace the import in `app/tests/test_locking.py` with:

```python
from app.infrastructure.locking.job_lock import (
    advisory_lock_key,
    acquire_job_lock,
    release_job_lock,
)
```

Rename `_advisory_lock_key(...)` assertions to `advisory_lock_key(...)`.

- [ ] **Step 2: Run the lock tests and verify the target module is missing**

Run:

```bash
python -m pytest app/tests/test_locking.py -v
```

Expected: FAIL during import because `app.infrastructure.locking.job_lock` does not exist yet.

- [ ] **Step 3: Implement the locking infrastructure with behavior identical to the current helpers**

Create `app/infrastructure/locking/job_lock.py`:

```python
import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session


def advisory_lock_key(job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_job_lock(db: Session, job_id: str) -> bool:
    lock_key = advisory_lock_key(job_id)
    if "sqlite" in str(db.get_bind().url):
        return True
    result = db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    ).scalar()
    return bool(result)


def release_job_lock(db: Session, job_id: str) -> None:
    lock_key = advisory_lock_key(job_id)
    if "sqlite" in str(db.get_bind().url):
        return
    db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": lock_key},
    )
```

Create `app/infrastructure/locking/__init__.py`:

```python
from app.infrastructure.locking.job_lock import (
    acquire_job_lock,
    advisory_lock_key,
    release_job_lock,
)

__all__ = ["acquire_job_lock", "advisory_lock_key", "release_job_lock"]
```

- [ ] **Step 4: Move ranking to the infrastructure import and remove lock implementation from `app.deps`**

In `app/domains/ranking/service.py`, replace:

```python
from app.deps import acquire_job_lock, release_job_lock
```

with:

```python
from app.infrastructure.locking.job_lock import acquire_job_lock, release_job_lock
```

In `app/deps.py`, delete `hashlib`, `_advisory_lock_key`, `acquire_job_lock`, and `release_job_lock`. Keep the database session and current auth behavior untouched in this task.

In `app/tests/test_contract.py`, replace the three lock-key tests to import `advisory_lock_key` from `app.infrastructure.locking.job_lock` and use that public name.

- [ ] **Step 5: Run lock and ranking contract tests**

Run:

```bash
python -m pytest app/tests/test_locking.py app/tests/test_contract.py app/tests/test_ranking.py -v
```

Expected: PASS. Ranking recalculation must still return the same versions/statuses and SQLite must still bypass PostgreSQL locks.

- [ ] **Step 6: Commit the lock extraction**

```bash
git add app/infrastructure/locking app/deps.py app/domains/ranking/service.py app/tests/test_locking.py app/tests/test_contract.py
git commit -m "refactor: move ranking locks to infrastructure"
```

---

### Task 3: Extract Cognito Authentication to Infrastructure

**Files:**
- Create: `app/infrastructure/auth/__init__.py`
- Create: `app/infrastructure/auth/cognito.py`
- Modify: `app/deps.py`
- Modify: `app/tests/test_auth_dependency.py`

**Interfaces:**
- Consumes: bearer access-token string and `AWS_REGION` environment value.
- Produces:
  - `class CognitoAuthenticationError(Exception)`
  - `get_cognito_client()` cached provider client
  - `validate_access_token(token: str) -> dict[str, str | None]`
- `app.deps.get_current_user(request: Request) -> dict[str, str | None]` remains the public FastAPI adapter.

- [ ] **Step 1: Add tests for the target Cognito infrastructure API**

Extend `app/tests/test_auth_dependency.py` with:

```python
import app.infrastructure.auth.cognito as cognito


def test_validate_access_token_normalizes_provider_response(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            assert AccessToken == "abc"
            return {
                "Username": "legacy-user",
                "UserAttributes": [
                    {"Name": "sub", "Value": "stable-sub"},
                    {"Name": "email", "Value": "person@example.com"},
                ],
            }

    monkeypatch.setattr(cognito, "get_cognito_client", lambda: FakeCognito())
    assert cognito.validate_access_token("abc") == {
        "sub": "stable-sub",
        "email": "person@example.com",
    }


def test_validate_access_token_wraps_provider_errors(monkeypatch):
    class FakeCognito:
        def get_user(self, *, AccessToken):
            raise RuntimeError("provider error")

    monkeypatch.setattr(cognito, "get_cognito_client", lambda: FakeCognito())
    with pytest.raises(cognito.CognitoAuthenticationError):
        cognito.validate_access_token("bad")
```

Update the invalid-token adapter test to monkeypatch `app.deps.cognito.validate_access_token` to raise `CognitoAuthenticationError`, so the test verifies the HTTP adapter/provider boundary instead of provider internals.

- [ ] **Step 2: Run auth tests and verify the new infrastructure import fails**

Run:

```bash
python -m pytest app/tests/test_auth_dependency.py -v
```

Expected: FAIL because `app.infrastructure.auth.cognito` does not exist yet.

- [ ] **Step 3: Implement Cognito provider module**

Create `app/infrastructure/auth/cognito.py`:

```python
import logging
import os

import boto3

logger = logging.getLogger(__name__)


class CognitoAuthenticationError(Exception):
    """Raised when Cognito cannot validate the supplied access token."""


_cognito_client = None


def get_cognito_client():
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client(
            "cognito-idp",
            region_name=os.getenv("AWS_REGION", "us-east-2"),
        )
    return _cognito_client


def validate_access_token(token: str) -> dict[str, str | None]:
    try:
        response = get_cognito_client().get_user(AccessToken=token)
    except Exception as exc:
        logger.warning("Auth validation failed: %s", exc)
        raise CognitoAuthenticationError() from exc

    attrs = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
    return {
        "sub": attrs.get("sub") or response.get("Username"),
        "email": attrs.get("email"),
    }
```

Create `app/infrastructure/auth/__init__.py`:

```python
from app.infrastructure.auth.cognito import (
    CognitoAuthenticationError,
    validate_access_token,
)

__all__ = ["CognitoAuthenticationError", "validate_access_token"]
```

- [ ] **Step 4: Reduce `app.deps` auth to an HTTP adapter**

Replace boto3/os/client code in `app/deps.py` with:

```python
from app.infrastructure.auth import cognito


def get_current_user(request: Request) -> dict[str, str | None]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided.")

    token = auth_header[7:]
    try:
        return cognito.validate_access_token(token)
    except cognito.CognitoAuthenticationError:
        raise HTTPException(status_code=401, detail="Token invalido o expirado.")
```

Do not catch arbitrary application exceptions in `app.deps`; provider failures are normalized by `cognito.validate_access_token`.

- [ ] **Step 5: Run auth plus endpoint regression tests**

Run:

```bash
python -m pytest app/tests/test_auth_dependency.py app/tests/test_contract.py app/tests/test_jobs.py app/tests/test_ranking.py -v
```

Expected: PASS with the exact same 401 details and normal authenticated endpoint behavior.

- [ ] **Step 6: Commit the Cognito extraction**

```bash
git add app/infrastructure/auth app/deps.py app/tests/test_auth_dependency.py
git commit -m "refactor: isolate cognito authentication infrastructure"
```

---

### Task 4: Introduce FastAPI Application Factory and Thin `main.py`

**Files:**
- Create: `app/bootstrap.py`
- Modify: `app/main.py`
- Modify: `app/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: existing routers, `Base`, `get_engine`, and current startup semantics.
- Produces: `app.bootstrap.create_app() -> FastAPI` and unchanged deployment entry point `app.main:app`.

- [ ] **Step 1: Change bootstrap tests to require a reusable application factory**

Extend `app/tests/test_bootstrap.py`:

```python
from app.bootstrap import create_app


def test_create_app_returns_distinct_fastapi_instances():
    first = create_app()
    second = create_app()
    assert first is not second
    assert first.title == second.title == "AI Recruiter API (PostgreSQL)"


def test_create_app_registers_critical_routes():
    paths = {route.path for route in create_app().routes}
    assert "/health" in paths
    assert "/api/jobs" in paths
    assert "/api/candidates" in paths
    assert "/api/jobs/{job_id}/ranking" in paths
    assert "/api/jobs/{job_id}/ranking/recalculate" in paths
```

- [ ] **Step 2: Run bootstrap tests and verify the factory import fails**

Run:

```bash
python -m pytest app/tests/test_bootstrap.py -v
```

Expected: FAIL because `app.bootstrap` is not implemented yet.

- [ ] **Step 3: Move FastAPI construction and registration into `app/bootstrap.py`**

Implement `app/bootstrap.py` with these focused helpers:

```python
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth_routes import router as auth_router
from app.db import Base, get_engine
from app.domains.candidates.router import assign_router, router as candidates_router
from app.domains.evaluations.router import router as evaluations_router
from app.domains.jobs.router import router as jobs_router
from app.domains.ranking.router import router as ranking_router
from app.health import router as health_router

logger = logging.getLogger(__name__)

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "https://ai.adrianguerra.net",
    "https://air.adrianguerra.net",
]


def _register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(jobs_router)
    app.include_router(candidates_router)
    app.include_router(assign_router)
    app.include_router(evaluations_router)
    app.include_router(ranking_router)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled error on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(status_code=500, content={"detail": "Error interno del servidor."})


def _register_startup(app: FastAPI) -> None:
    @app.on_event("startup")
    def on_startup() -> None:
        db_url = os.getenv("DATABASE_URL", "")
        if "sqlite" in db_url or not db_url:
            logger.info("Skipping table creation (non-PostgreSQL URL).")
            return
        logger.info("Creating tables if not present ...")
        Base.metadata.create_all(bind=get_engine())
        logger.info("Tables ready.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Recruiter API (PostgreSQL)",
        description="Ranking de candidatos con PostgreSQL + advisory locks",
        version="2.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_routes(app)
    _register_exception_handlers(app)
    _register_startup(app)
    return app
```

- [ ] **Step 4: Reduce `app/main.py` to the deployment entry point**

Replace the file with:

```python
"""ASGI entry point for AI Recruiter."""

from app.bootstrap import create_app

app = create_app()
```

- [ ] **Step 5: Run application-factory and endpoint contract tests**

Run:

```bash
python -m pytest app/tests/test_bootstrap.py app/tests/test_health.py app/tests/test_contract.py -v
```

Expected: PASS. `app.main:app` remains importable and all current critical routes remain registered.

- [ ] **Step 6: Commit the composition-root extraction**

```bash
git add app/bootstrap.py app/main.py app/tests/test_bootstrap.py
git commit -m "refactor: add fastapi application factory"
```

---

### Task 5: Centralize Stable Environment Configuration

**Files:**
- Create: `app/config.py`
- Modify: `app/bootstrap.py`
- Modify: `app/infrastructure/auth/cognito.py`
- Modify: `app/tests/test_bootstrap.py`
- Modify: `app/tests/test_auth_dependency.py`

**Interfaces:**
- Produces:
  - `DEFAULT_AWS_REGION = "us-east-2"`
  - `DEFAULT_CORS_ORIGINS: tuple[str, ...]`
  - `@dataclass(frozen=True) class Settings`
  - `load_settings() -> Settings`
- `Settings` fields: `aws_region: str`, `database_url: str`, `cors_origins: tuple[str, ...]`.

- [ ] **Step 1: Add direct settings tests**

Add to `app/tests/test_bootstrap.py`:

```python
from app.config import DEFAULT_CORS_ORIGINS, load_settings


def test_load_settings_preserves_existing_defaults(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = load_settings()
    assert settings.aws_region == "us-east-2"
    assert settings.database_url == ""
    assert settings.cors_origins == DEFAULT_CORS_ORIGINS


def test_load_settings_reads_existing_environment_names(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    settings = load_settings()
    assert settings.aws_region == "us-west-2"
    assert settings.database_url == "postgresql://example"
```

- [ ] **Step 2: Run the new settings tests and verify the module is missing**

Run:

```bash
python -m pytest app/tests/test_bootstrap.py -v
```

Expected: FAIL because `app.config` is not implemented yet.

- [ ] **Step 3: Implement the small configuration boundary**

Create `app/config.py`:

```python
from dataclasses import dataclass
import os

DEFAULT_AWS_REGION = "us-east-2"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "https://ai.adrianguerra.net",
    "https://air.adrianguerra.net",
)


@dataclass(frozen=True)
class Settings:
    aws_region: str
    database_url: str
    cors_origins: tuple[str, ...]


def load_settings() -> Settings:
    return Settings(
        aws_region=os.getenv("AWS_REGION", DEFAULT_AWS_REGION),
        database_url=os.getenv("DATABASE_URL", ""),
        cors_origins=DEFAULT_CORS_ORIGINS,
    )
```

- [ ] **Step 4: Make bootstrap and Cognito consume settings instead of direct environment access**

In `app/bootstrap.py`:

```python
from app.config import load_settings
```

Inside `create_app()`:

```python
settings = load_settings()
```

Use `list(settings.cors_origins)` for CORS registration. Pass `settings.database_url` into a focused startup helper so startup no longer calls `os.getenv` directly:

```python
def _register_startup(app: FastAPI, *, database_url: str) -> None:
    @app.on_event("startup")
    def on_startup() -> None:
        if "sqlite" in database_url or not database_url:
            logger.info("Skipping table creation (non-PostgreSQL URL).")
            return
        Base.metadata.create_all(bind=get_engine())
```

In `app/infrastructure/auth/cognito.py`, replace direct `os.getenv` with:

```python
from app.config import load_settings


def get_cognito_client():
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client(
            "cognito-idp",
            region_name=load_settings().aws_region,
        )
    return _cognito_client
```

Do not rename `AWS_REGION` or `DATABASE_URL`.

- [ ] **Step 5: Run configuration, auth, bootstrap, and contract tests**

Run:

```bash
python -m pytest app/tests/test_bootstrap.py app/tests/test_auth_dependency.py app/tests/test_contract.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit configuration cleanup**

```bash
git add app/config.py app/bootstrap.py app/infrastructure/auth/cognito.py app/tests/test_bootstrap.py app/tests/test_auth_dependency.py
git commit -m "refactor: centralize application settings"
```

---

### Task 6: Add Dependency Boundary Guard Tests

**Files:**
- Create: `app/tests/test_architecture_boundaries.py`
- Existing transitional routers: `app/domains/jobs/router.py`, `app/domains/candidates/router.py`, `app/domains/evaluations/router.py`, `app/domains/ranking/router.py`

**Interfaces:**
- Consumes: Python source files under `app/`.
- Produces: CI-enforced architecture constraints without adding runtime dependencies.

- [ ] **Step 1: Add an AST helper and explicit transitional `app.crud` allow-list**

Create `app/tests/test_architecture_boundaries.py`:

```python
import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]

CRUD_ROUTER_ALLOWLIST = {
    "domains/jobs/router.py",
    "domains/candidates/router.py",
    "domains/evaluations/router.py",
    "domains/ranking/router.py",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result.add(module)
            if module == "app":
                result.update(f"app.{alias.name}" for alias in node.names)
    return result


def _python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
```

- [ ] **Step 2: Add a guard that prevents expansion of the compatibility facade**

```python
def test_only_documented_transitional_routers_import_app_crud():
    violations = []
    routers = APP_ROOT / "domains"
    for path in routers.rglob("router.py"):
        relative = path.relative_to(APP_ROOT).as_posix()
        if "app.crud" in _imports(path) and relative not in CRUD_ROUTER_ALLOWLIST:
            violations.append(relative)
    assert violations == []
```

This test intentionally allows only the four current transitional router consumers. Future domain plans must remove entries as imports are migrated; new entries are not permitted.

- [ ] **Step 3: Add direction guards for routers, infrastructure, and locking**

```python
def test_domain_non_router_modules_do_not_import_domain_routers():
    violations = []
    for path in _python_files(APP_ROOT / "domains"):
        if path.name == "router.py":
            continue
        if any(name.endswith(".router") and name.startswith("app.domains.") for name in _imports(path)):
            violations.append(path.relative_to(APP_ROOT).as_posix())
    assert violations == []


def test_infrastructure_does_not_import_domain_routers():
    violations = []
    for path in _python_files(APP_ROOT / "infrastructure"):
        if any(name.endswith(".router") and name.startswith("app.domains.") for name in _imports(path)):
            violations.append(path.relative_to(APP_ROOT).as_posix())
    assert violations == []


def test_locking_is_not_imported_from_deps_outside_http_adapters():
    violations = []
    forbidden = {"app.deps.acquire_job_lock", "app.deps.release_job_lock"}
    for path in _python_files(APP_ROOT):
        if path == APP_ROOT / "deps.py":
            continue
        if _imports(path) & forbidden:
            violations.append(path.relative_to(APP_ROOT).as_posix())
    assert violations == []
```

Because `from app.deps import acquire_job_lock` is represented by the base module `app.deps`, extend `_imports` for `ImportFrom` to also add fully qualified imported symbols:

```python
elif isinstance(node, ast.ImportFrom):
    module = node.module or ""
    result.add(module)
    result.update(f"{module}.{alias.name}" for alias in node.names if module)
```

Use this version in the final helper so the locking guard is effective.

- [ ] **Step 4: Run the architecture guards**

Run:

```bash
python -m pytest app/tests/test_architecture_boundaries.py -v
```

Expected: PASS against the foundation architecture after Tasks 2-5.

- [ ] **Step 5: Prove the guard is meaningful before keeping it**

Temporarily add a local, uncommitted forbidden import such as `from app.deps import acquire_job_lock` to `app/domains/ranking/service.py`, run:

```bash
python -m pytest app/tests/test_architecture_boundaries.py::test_locking_is_not_imported_from_deps_outside_http_adapters -v
```

Expected: FAIL and report `domains/ranking/service.py`. Revert the temporary line immediately, rerun the test, and verify PASS. Do not commit the temporary violation.

- [ ] **Step 6: Commit the architecture guards**

```bash
git add app/tests/test_architecture_boundaries.py
git commit -m "test: enforce modular dependency boundaries"
```

---

### Task 7: Run Full Regression Gates and Prepare the Foundation PR

**Files:**
- Verify only; no production-code changes expected.
- If a regression is found, fix it in the task that introduced it and rerun the affected task gate before this final gate.

**Interfaces:**
- Consumes: all outputs from Tasks 1-6.
- Produces: a branch suitable for a single foundation PR into `main`.

- [ ] **Step 1: Run Python syntax validation**

```bash
python -m compileall app
```

Expected: exit code 0.

- [ ] **Step 2: Run the complete backend SQLite test suite**

```bash
python -m pytest app/tests -v
```

Expected: PASS with no new failures.

- [ ] **Step 3: Run the repository's existing PostgreSQL smoke command exactly as defined by CI**

Inspect `.github/workflows/` and execute the same PostgreSQL smoke command used by the active workflow rather than inventing a new command. Expected: PASS, including ranking advisory-lock coverage.

- [ ] **Step 4: Run frontend regression gates even though frontend code is unchanged**

```bash
npm --prefix frontend-react run lint
npm --prefix frontend-react run test
npm --prefix frontend-react run build
```

Expected: all three commands exit 0 and ASIATI branding remains untouched.

- [ ] **Step 5: Confirm no accidental schema or frontend changes**

Run:

```bash
git diff main...HEAD -- app/models.py alembic frontend-react
```

Expected: no database-schema/Alembic changes and no `frontend-react` changes from this architecture plan.

- [ ] **Step 6: Confirm `app.deps` no longer owns provider/lock implementation**

Run:

```bash
grep -nE "boto3|hashlib|pg_try_advisory_lock|pg_advisory_unlock|_cognito_client" app/deps.py
```

Expected: no matches.

- [ ] **Step 7: Confirm ranking imports locks only from infrastructure**

Run:

```bash
grep -n "lock" app/domains/ranking/service.py
```

Expected: `acquire_job_lock` and `release_job_lock` resolve from `app.infrastructure.locking.job_lock`, with no locking import from `app.deps`.

- [ ] **Step 8: Commit any verification-only documentation adjustment only if required**

If no tracked files changed during verification, do not create an empty commit. If a command/document path needed correction, update this plan in the same branch and commit only that documentation correction.

- [ ] **Step 9: Open one foundation PR into `main`**

PR title:

```text
refactor: establish modular monolith foundation
```

PR body must state:

```markdown
## Scope
- extract PostgreSQL advisory locks to infrastructure
- extract Cognito validation to infrastructure
- add FastAPI application factory/composition root
- centralize stable environment-derived settings
- add architecture dependency guards

## Compatibility
- no API contract changes
- no database migrations
- no environment-variable renames
- no Bedrock/ranking/storage behavior changes
- no frontend/ASIATI branding changes

## Verification
- backend pytest suite
- contract tests
- PostgreSQL smoke tests
- frontend lint/tests/build
```

Do not merge until all configured CI jobs are green.

---

## Plan Self-Review

- Spec coverage: all foundation requirements are mapped to Tasks 1-7; frontend/domain decomposition remains explicitly out of scope.
- Placeholder scan: the plan contains no implementation placeholders; the only environment-specific instruction is to execute the repository's already-defined PostgreSQL smoke command from CI so local verification exactly matches the source of truth.
- Type consistency: locking uses `advisory_lock_key`, `acquire_job_lock`, and `release_job_lock` consistently; Cognito uses `CognitoAuthenticationError` and `validate_access_token`; configuration consistently exposes `load_settings() -> Settings`; bootstrap consistently exposes `create_app() -> FastAPI`.
- Rollback: every production refactor is separated into its own commit and requires no data rollback.
