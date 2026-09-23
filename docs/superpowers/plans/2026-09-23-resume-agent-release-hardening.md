# Resume Agent Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the eight release-blocking gaps found after the responsive/SPA regression work so the Resume Agent fails closed, reports incomplete vacancy syncs, preserves incremental idempotency, and remains usable with large Indeed workspaces.

**Architecture:** Keep the stable `IndeedBrowserUse` driver and harden the vacancy/session compatibility layer around explicit contracts. Remove unsafe geometric assumptions where exact identity is impossible, make vacancy collection integrity explicit, and extract sync orchestration into a testable controller so release tests execute behavior rather than inspect source text.

**Tech Stack:** Python 3.12 Windows agent, Browser Use/CDP, Playwright browser fixtures, Tkinter UI, httpx backend client, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-22-resume-agent-incremental-and-vacancy-sync-design.md`

## Global Constraints

- Keep PR #84 isolated from `main` until the release gate is green and manually approved.
- `Actualizar vacantes` must never trigger Gmail/application sync or candidate CV processing.
- `Sincronizar todo` ordering remains vacancies -> incremental applications -> candidate worker only when pending work exists.
- Never create or reconcile a vacancy from title alone when stable Indeed identity is unavailable.
- A partial vacancy crawl must not be reported as successful.
- A visible login/CAPTCHA/challenge remains a global blocker; hidden challenge infrastructure must not block authenticated workspaces.
- Preserve the existing Indeed and AI description-source semantics.

## Review Focus

- SPA row identity after reload/reorder: ambiguous duplicate rows must fail closed rather than use geometry to guess.
- Dynamic row text/counters: a unique vacancy should remain recoverable if candidate counts change.
- Virtualized DOM recycling: a stale token must not click a node whose content/identity changed.
- Large workspaces: virtualized/paginated discovery must cover 400+ jobs without truncating at the first viewport or 500 raw DOM nodes.
- Partial collection: any discovered row that cannot be opened or resolved to a stable provider identity must surface an incomplete-sync error.

---

### Task 1: Harden SPA row recovery

**Files:**
- Modify: `tools/indeed_resume_agent/vacancy_click_recovery.py`
- Test: `tools/indeed_resume_agent/tests/test_release_hardening.py`

**Interfaces:**
- Consumes listing rows containing `clickToken`, `externalJobKey`, `title`, `rowText`, `rowPosition`.
- Produces `_click_listing_row(...) -> bool` semantics: true only when the exact or uniquely recoverable vacancy is clicked.

- [ ] Add RED tests for reordered identical rows, changed counters on a unique title, and recycled DOM tokens.
- [ ] Verify all three fail for the intended reason.
- [ ] Implement token validation and conservative fallback matching; remove geometric guessing for multiple identical rows.
- [ ] Verify targeted tests and full agent suite green.

### Task 2: Make partial vacancy sync impossible to report as success

**Files:**
- Modify: `tools/indeed_resume_agent/vacancy_sync.py`
- Modify: `tools/indeed_resume_agent/ui_v2.py`
- Test: `tools/indeed_resume_agent/tests/test_release_hardening.py`

**Interfaces:**
- Produces `INDEED_JOB_SYNC_INCOMPLETE` when at least one discovered row cannot be opened/resolved.
- UI maps that safe code to an explicit attention message.

- [ ] Add RED tests for click failure and detail-without-stable-id.
- [ ] Implement incomplete accounting and fail closed before `api.sync_jobs` is called.
- [ ] Verify the UI exposes the safe failure rather than generic success/zero jobs.

### Task 3: Harden authentication classification

**Files:**
- Modify: `tools/indeed_resume_agent/runtime_compat.py`
- Test: `tools/indeed_resume_agent/tests/test_browser_auth_detection.py`

**Interfaces:**
- `_requires_human(cdp) -> bool` must prefer hard challenge evidence and authenticated workspace structure over mutable marketing/help copy.

- [ ] Add RED tests for authenticated jobs/candidates workspaces with changed copy and visible challenge overlays.
- [ ] Implement structural authenticated evidence that does not require one exact phrase pair.
- [ ] Keep explicit login URL/copy and visible challenge behavior blocking.

### Task 4: Execute real sync orchestration in tests

**Files:**
- Create: `tools/indeed_resume_agent/sync_controller.py`
- Modify: `tools/indeed_resume_agent/ui_v2.py`
- Modify: `tools/indeed_resume_agent/tests/test_release_contracts.py`

**Interfaces:**
- Controller executes `sync_jobs_only()` and `sync_all()` against injected worker/api/browser/callbacks.
- UI delegates command behavior to the controller; tests invoke the same production code directly.

- [ ] Replace source-inspection tests with RED behavioral tests.
- [ ] Extract minimal controller preserving current visible states.
- [ ] Verify jobs-only never calls application sync and full sync ordering is vacancies -> applications -> worker.

### Task 5: Prove incremental no-op does not browse completed candidates

**Files:**
- Test: `tools/indeed_resume_agent/tests/test_release_hardening.py`
- Modify controller only if required by the failing contract.

- [ ] Add test with `pending=0` after incremental sync and a browser that raises if candidate fetch is called.
- [ ] Ensure no-op completion does not start candidate work; if pending >0, worker resumes normally.

### Task 6: Prove 400+ vacancy completeness

**Files:**
- Modify: `tools/indeed_resume_agent/runtime_compat.py` and/or `vacancy_sync.py`
- Test: `tools/indeed_resume_agent/tests/test_release_hardening.py`

- [ ] Add a virtualized/paginated fixture producing at least 425 unique jobs across scroll rounds/pages.
- [ ] Assert all stable identities are collected exactly once.
- [ ] Remove any raw-node/round behavior that truncates legitimate results while keeping bounded execution.

### Task 7: Remove runtime-patch blind spots from packaging gate

**Files:**
- Modify: `tools/indeed_resume_agent/self_test.py`
- Test: packaging/self-test tests as applicable.

- [ ] Add a packaged preflight that imports/installs runtime compatibility and click recovery, exercises their callable contracts against a local synthetic page, and never contacts production.
- [ ] Keep Chrome/CDP and Credential Manager checks.

### Task 8: Final release gate

**Files:**
- Review all 13+ changed PR files and CI workflow.

- [ ] Run full Resume Agent suite on Linux and Windows.
- [ ] Run backend SQLite + Postgres smoke + frontend tests/build.
- [ ] Build Windows onedir.
- [ ] Execute packaged binary `--self-test`.
- [ ] Publish artifact only after all previous steps pass.
- [ ] Perform final diff/code-review pass; Critical/Important findings receive one RED->GREEN fix pass before release recommendation.
