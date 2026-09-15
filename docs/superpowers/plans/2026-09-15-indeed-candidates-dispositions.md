# Indeed Candidates + Disposition Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Indeed Job Sync adapter with Retrieve Candidates, provider-neutral application status, Disposition Sync, and minimal Jobs UI controls while remaining fully testable without live Indeed credentials.

**Architecture:** Keep Indeed-specific state in `app/domains/indeed` and dedicated link/event tables. Reuse existing owner-scoped candidate identity and JobCandidate assignment logic. Local application status belongs to JobCandidate; provider mapping and outbound identifiers remain in the Indeed adapter.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, httpx, PostgreSQL, React, Axios, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-15-indeed-candidates-dispositions-design.md`

## Global Constraints

- Work only on `feat/indeed-integration-foundation`.
- `INDEED_ENABLED=false` remains the default.
- No live Indeed API calls in tests or CI.
- Never log OAuth secrets/tokens or full resume URLs.
- All provider persistence and queries are owner-scoped.
- Do not acknowledge a candidate batch if local batch processing fails.
- Disposition batches are sorted oldest-first and limited to 25.
- Core Candidate remains provider-neutral.

---

### Task 1: Add provider-neutral application status and Indeed persistence

**Files:**
- Modify: `app/models.py`
- Create: `app/migrations/versions/005_indeed_candidates_dispositions.py`
- Test: `app/tests/test_indeed_candidate_sync.py`

**Interfaces:**
- Produces `JobCandidate.application_status`, `JobCandidate.status_changed_at`.
- Produces `IndeedCandidateLink`, `IndeedCandidateSyncState`, `IndeedDispositionEvent`.

- [ ] Add tests asserting the ORM fields/tables, defaults, owner/asset uniqueness, and relationship integrity.
- [ ] Verify the tests fail against the pre-task code.
- [ ] Add ORM models and migration 005.
- [ ] Run targeted tests until green.
- [ ] Commit.

### Task 2: Implement Retrieve Candidates mapping and durable batch processing

**Files:**
- Create: `app/domains/indeed/candidates.py`
- Modify: `app/domains/indeed/repository.py`
- Modify: `app/domains/indeed/service.py`
- Test: `app/tests/test_indeed_candidate_sync.py`

**Interfaces:**
- Produces `fetch_candidate_assets(db, owner_sub, client=None, settings=None, limit=25) -> dict`.
- Consumes existing `IndeedClient.execute()` and `IndeedJobLink.sourced_posting_id`.

- [ ] Add fake-client tests for a supported Interested Candidate asset, unknown asset type, job-link resolution, repeated asset idempotency, and a failed batch that does not advance acknowledgment state.
- [ ] Verify RED.
- [ ] Implement the exact `fetchAssets` GraphQL document with metadata, candidate contact, resume PDF, job sourcedPostingId, and tracking fields.
- [ ] Reuse existing candidate email/phone identity logic; create/reuse Candidate and idempotently attach JobCandidate.
- [ ] Persist provider link/source/resume metadata and sync token only after successful processing.
- [ ] Run targeted tests until GREEN.
- [ ] Commit.

### Task 3: Add local application-status service and disposition event creation

**Files:**
- Modify: `app/domains/candidates/repository.py`
- Modify: `app/domains/candidates/service.py`
- Modify: `app/domains/candidates/router.py`
- Create: `app/domains/indeed/dispositions.py`
- Test: `app/tests/test_indeed_dispositions.py`

**Interfaces:**
- Produces `set_application_status(db, owner_sub, job_id, candidate_id, status)`.
- Produces `map_local_status(status) -> str | None`.
- Produces `queue_disposition_for_application(...)`.
- Endpoint: `PUT /api/jobs/{job_id}/candidates/{candidate_id}/status` body `{"status":"INTERVIEW"}`.

- [ ] Add tests for valid states, invalid state 422, tenant isolation, no-op duplicate status, and event creation only for an Indeed-linked candidate with a mapped state.
- [ ] Verify RED.
- [ ] Implement status update and timestamp handling.
- [ ] Implement Indeed status mapper: APPLIED->NEW, SCREENING->POSITIVELY_SCREENED, INTERVIEW->INTERVIEW, OFFER->OFFER_MADE, HIRED->HIRED, REJECTED->NOT_SELECTED, WITHDRAWN->WITHDRAWN, ON_HOLD->None.
- [ ] Queue durable disposition events without making network calls.
- [ ] Run targeted tests until GREEN.
- [ ] Commit.

### Task 4: Implement Disposition Sync transport and partial-failure handling

**Files:**
- Modify: `app/domains/indeed/dispositions.py`
- Modify: `app/domains/indeed/repository.py`
- Modify: `app/domains/indeed/service.py`
- Test: `app/tests/test_indeed_dispositions.py`

**Interfaces:**
- Produces `sync_dispositions(db, owner_sub, client=None, settings=None, limit=25) -> dict`.
- Uses GraphQL `partnerDisposition.send`.

- [ ] Add tests proving oldest-first ordering and max-25 selection.
- [ ] Add identifier tests for priority Indeed Apply ID -> ITTK -> Universal Apply ID -> alternate EmployerJob ID + email.
- [ ] Add fake provider response tests for all-success and partial-failure cases.
- [ ] Verify RED.
- [ ] Build exactly one `identifiedBy` method per event.
- [ ] Send `rawDispositionStatus`, `dispositionStatus`, ATS name, source, and RFC3339 status-change time.
- [ ] Mark successes SENT and provider failures FAILED with rationale; increment attempts.
- [ ] Run targeted tests until GREEN.
- [ ] Commit.

### Task 5: Expose manual candidate/disposition sync APIs

**Files:**
- Modify: `app/domains/indeed/router.py`
- Modify: `app/domains/indeed/schemas.py`
- Test: `app/tests/test_indeed_routes.py`

**Interfaces:**
- `POST /api/integrations/indeed/candidates/sync`
- `POST /api/integrations/indeed/dispositions/sync`

- [ ] Add authenticated route tests for success and 404/422/502/503 mapping.
- [ ] Verify RED.
- [ ] Add thin router adapters that call service boundaries only.
- [ ] Run route tests until GREEN.
- [ ] Commit.

### Task 6: Add minimal Jobs frontend controls

**Files:**
- Modify: `frontend-react/src/pages/Jobs.jsx`
- Modify: `frontend-react/src/pages/Jobs.css`
- Test: `frontend-react/src/__tests__/Jobs.test.jsx` or nearest existing Jobs test file.

**Interfaces:**
- Job form sends `country_code`, `city`, `employment_type`, `public_slug`.
- UI calls Indeed status/publish/status-refresh/candidate-sync/expire endpoints.

- [ ] Add/extend UI tests for publication metadata and disabled/not-configured Indeed state.
- [ ] Verify RED.
- [ ] Add form fields without breaking legacy title/description workflow.
- [ ] Add Indeed integration status on Jobs page and buttons with loading/error states.
- [ ] Keep controls hidden/disabled appropriately when integration is disabled.
- [ ] Run frontend lint/tests/build until GREEN.
- [ ] Commit.

### Task 7: Full integration verification and PR cleanup

- [ ] Run full GitHub Actions on the final head.
- [ ] Require frontend lint/tests/build green.
- [ ] Require backend full pytest + contract tests green.
- [ ] Require PostgreSQL smoke green, including migration chain through 005.
- [ ] Review PR diff for unrelated formatting/refactors and remove noise.
- [ ] Update PR description to describe Job Sync + Retrieve Candidates + Disposition Sync and explicitly list remaining real-account E2E/certification work.
- [ ] Mark PR ready for review only after both workflows are successful.