# Runtime Secret Externalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove embedded PostgreSQL credentials from the repository and make production database configuration an injected secret while keeping non-secret AWS identifiers separate.

**Architecture:** Runtime code and deploy scripts consume `DATABASE_URL` exclusively from the environment. GitHub Actions supplies the production value from an Actions secret; non-secret AWS identifiers remain configuration/variables rather than secrets. Regression tests scan the production runtime/deploy surfaces so the credential literal cannot be reintroduced.

**Tech Stack:** FastAPI, SQLAlchemy, Bash, GitHub Actions, pytest

**Spec:** User-requested security hardening of `donardi-1997/ai-recruiter`.

## Global Constraints

- Never commit a production database password or connection URL.
- Keep tests isolated on `sqlite:///:memory:` through `app/tests/conftest.py`.
- Do not merge until the GitHub `DATABASE_URL` secret exists and CI is green.
- Treat AWS account IDs, resource IDs, ARNs and distribution IDs as configuration, not credentials.
- Do not rewrite Git history or delete the stale `master` branch without explicit approval.

---

### Task 1: Regression guard for embedded database credentials

**Files:**
- Create: `app/tests/test_sensitive_runtime_config.py`

**Interfaces:**
- Consumes: repository files under `app/`, `scripts/`, and `.github/workflows/`.
- Produces: a failing guard while `postgres:postgres` remains embedded.

- [ ] Write a test that rejects `postgres:postgres` in production runtime/deploy files.
- [ ] Verify the test fails on the current branch.
- [ ] Commit the red test.

### Task 2: Require DATABASE_URL in runtime scripts and application

**Files:**
- Modify: `app/db.py`
- Modify: `scripts/deploy-api.sh`
- Modify: `scripts/deploy-worker.sh`
- Test: `app/tests/test_sensitive_runtime_config.py`

**Interfaces:**
- Consumes: environment variable `DATABASE_URL`.
- Produces: fail-closed application and deployment scripts with no password fallback.

- [ ] Replace the SQLAlchemy fallback URL with `os.environ["DATABASE_URL"]`.
- [ ] Make both deploy scripts require `DATABASE_URL` using Bash `${DATABASE_URL:?...}` validation.
- [ ] Pass `DATABASE_URL` through container creation and rollback paths.
- [ ] Run targeted and full backend tests.

### Task 3: Inject production DATABASE_URL from GitHub Actions

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Test: `app/tests/test_sensitive_runtime_config.py`

**Interfaces:**
- Consumes: GitHub Actions secret `DATABASE_URL`.
- Produces: migrations, API, and worker deployments using the injected secret.

- [ ] Add `DATABASE_URL: ${{ secrets.DATABASE_URL }}` to the production deploy environment.
- [ ] Replace inline PostgreSQL URLs in migration/backfill containers with `$DATABASE_URL`.
- [ ] Pass `DATABASE_URL` to `deploy-api.sh` and `deploy-worker.sh`.
- [ ] Verify no database credential literal remains.

### Task 4: Separate non-secret configuration

**Files:**
- Modify: `.env.example`
- Review: `.github/workflows/deploy.yml`, `scripts/deploy-api.sh`, `scripts/deploy-worker.sh`

**Interfaces:**
- Consumes: GitHub Variables / environment variables for non-secret identifiers.
- Produces: documented secret-vs-variable boundary.

- [ ] Add an empty `DATABASE_URL=` placeholder to `.env.example`.
- [ ] Keep public resource identifiers out of the secret inventory.
- [ ] Document which values belong in GitHub Secrets vs GitHub Variables.

### Task 5: Stale public master branch follow-up

**Files:**
- Review only: `master/main.py`, `master/app.py`, `master/test_kb.py`

**Interfaces:**
- Consumes: current repository branch metadata.
- Produces: a cleanup recommendation without destructive branch deletion.

- [ ] Confirm `master` is still the default branch and contains stale infrastructure/candidate identifiers.
- [ ] Change default branch to `main` when an authorized repository-settings path is available.
- [ ] Ask for explicit approval before deleting `master` or rewriting history.
