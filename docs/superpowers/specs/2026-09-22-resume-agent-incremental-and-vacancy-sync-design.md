# Resume Agent Incremental Sync and Vacancy Refresh Design

## Goal

Make the ASIATI Resume Agent efficient for repeated daily use by ensuring `Sincronizar todo` processes only new or genuinely pending work, while adding a separate `Actualizar vacantes` action that refreshes Indeed vacancies and their original descriptions without touching candidates or CV downloads.

No change in this design may cause an already completed candidate/CV to be reopened in Indeed merely because the operator presses `Sincronizar todo` again.

## Current behavior and root cause

The Gmail mailbox layer is already durable and incremental. `sync_gmail_mailbox()` persists a Gmail history cursor and uses Gmail History after bootstrap. Therefore Gmail does not need to be redesigned.

The avoidable retraversal is currently produced by the Resume Agent orchestration around the mailbox sync:

- `AgentApiClient.sync_all()` repeatedly calls `/api/agents/indeed-resume/sync` until bootstrap/recovery pages are exhausted.
- every `/sync` call currently invokes `reconcile_existing_indeed_candidates()`;
- that reconciliation queries all owner-scoped `IndeedCandidateLink + Candidate + Job` rows, even when Gmail found no new application;
- `compact_duplicate_application_tasks()` currently requeues historical `INDEED_CANDIDATE_AMBIGUOUS` tasks whenever sync runs, which can turn an old review case back into browser work repeatedly.

The queue itself already protects completed canonical resumes reasonably well, so the design should preserve that behavior and remove unnecessary global reconciliation rather than replace the queue model.

## Product behavior

### `Sincronizar todo`

This becomes the normal incremental daily action.

It performs:

1. refresh Indeed vacancies first;
2. run Gmail discovery from the persisted cursor;
3. process only newly created/changed application records;
4. compact duplicates only in the affected candidate/job set;
5. reconcile only candidate/job records affected by this sync;
6. claim and process only queue tasks that are genuinely pending/retryable;
7. leave completed candidates, completed CVs and unresolved historical review cases untouched unless new evidence makes them actionable.

The second run with no provider changes should finish quickly and should produce zero new candidate browser work.

### `Actualizar vacantes`

This is a separate operator action.

It performs only:

1. validate the existing Indeed browser session;
2. navigate to the approved Indeed Employers jobs workspace;
3. enumerate current open/paused vacancies;
4. extract stable vacancy identity, title, state, location and original description;
5. send vacancy snapshots to the backend for idempotent reconciliation;
6. update `indeed_description` without overwriting `ai_description`;
7. finish without Gmail discovery, candidate reconciliation or resume queue processing.

The action must be safe to run while there are no candidate changes.

## Source-of-truth rules

- Indeed Employers is the canonical source for vacancy discovery and original vacancy descriptions.
- Gmail is the discovery source for applications only and must not create vacancies.
- Candidate identity must never be inferred only from normalized name.
- Same canonical candidate + same vacancy + multiple applications: newest application is operational.
- Same canonical candidate + different vacancies: one candidate remains associated with each vacancy independently.
- A completed canonical resume is terminal for that candidate/job version unless a newer application or provider resume version introduces new work.

## Incremental unit of work

A candidate alone is not a sufficient idempotency key.

The backend should reason in terms of an application/version identity containing, where available:

- canonical `candidate_id`;
- `job_id`;
- application/provider event identity;
- application `staged_at` or Gmail event timestamp;
- provider resume/link identity.

This means:

- an old completed application is skipped;
- the same candidate applying again to the same vacancy can create new work when the application is newer;
- the same candidate applying to another vacancy remains valid independent work;
- a newer provider resume can create new work even if the person already exists.

## Backend incremental reconciliation

### Preserve Gmail cursor semantics

Keep `mailbox_sync.py` bootstrap, recovery and incremental Gmail cursor behavior unchanged except where additional result metadata is needed.

### Return affected identities from Gmail ingestion

The sync service should collect the candidate/job/application identities that were created or materially changed during the current Gmail page.

Reconciliation must use those affected identities instead of scanning every Indeed candidate link on every page.

### Historical bootstrap

During a first-ever bootstrap or explicit recovery after an expired Gmail history cursor, historical pages may discover many records. Reconciliation may operate page-by-page on only the identities discovered by each page.

Do not run a full owner-wide candidate reconciliation after every bootstrap page.

### Existing backlog compatibility

One bounded one-time backlog reconciliation is still necessary for installations that predate incremental tracking. It must be represented by a durable completion marker/cursor so it does not repeat on every button press.

Do not use only an in-memory flag.

## Review/attention semantics

Historical `INDEED_CANDIDATE_AMBIGUOUS` tasks must not be automatically requeued on every incremental sync.

They may be requeued when one of these conditions is true:

- the operator explicitly selects `Retry attention`;
- a newer application/provider link for the same candidate/job changes the evidence available for matching;
- a future explicit maintenance/reprocess operation requests it.

Otherwise the old task remains visible in `Needs attention` without consuming browser work or blocking the queue.

Candidate-level attention continues to be non-blocking. Authentication/MFA/CAPTCHA remains globally blocking.

## Vacancy synchronization

The existing persistent Browser Use/CDP session remains the only Indeed browser owner.

### Browser extraction

Add deterministic vacancy discovery to the Resume Agent browser driver using:

`https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false&createdOnIndeed=true&tab=0&sortDirection=DESC&sortField=datePostedOnIndeed`

For every vacancy, extract a stable provider identity before automatic creation/reconciliation.

Minimum snapshot:

- `external_job_key`;
- `title`;
- `description`;
- `status`;
- `location` when available;
- `posted_at` when available;
- internal source URL when useful for diagnostics.

A new local vacancy must not be created automatically without a stable provider identity and a non-empty original description.

### Description semantics

On refresh:

- update `job.indeed_description` only when the newly extracted description is non-empty;
- if `active_description_source == "indeed"`, update effective `job.description` too;
- if `active_description_source == "ai"`, preserve both `job.ai_description` and effective AI description;
- never replace a non-empty Indeed description with an empty scrape;
- do not change the recruiter-selected active source automatically.

### Change fingerprint

Persist or derive a stable content fingerprint for the provider snapshot so unchanged vacancies can be reported as unchanged and avoid unnecessary writes/evaluation invalidation.

The fingerprint should include fields whose changes matter operationally, at minimum normalized original description plus relevant neutral vacancy fields.

## API boundaries

Keep the least-privilege agent API model.

Recommended actions:

- existing `/api/agents/indeed-resume/sync` evolves into one bounded incremental application-sync page;
- add a vacancy batch endpoint such as `POST /api/agents/indeed-resume/jobs/sync`;
- add enough result metadata for the desktop UI to display incremental counts;
- do not expose provider cookies, authentication material or unnecessary provider URLs.

A separate force/reprocess endpoint is not required for this delivery. Existing retry controls remain the maintenance path.

## Desktop orchestration

The desktop agent must serialize browser-owning actions.

While candidate CV processing or vacancy extraction owns Chrome/CDP:

- `Sincronizar todo` cannot start another sync;
- `Actualizar vacantes` cannot start concurrently;
- Diagnostic mode cannot mutate navigation concurrently.

The UI should disable or safely ignore conflicting actions and expose the active phase.

### `Sincronizar todo` phases

1. `SYNCING_JOBS`
2. `SYNCING_APPLICATIONS`
3. `SYNC_READY`
4. normal worker queue processing
5. final incremental summary

### `Actualizar vacantes` phases

1. `SYNCING_JOBS`
2. `JOBS_SYNC_COMPLETED` or `JOBS_SYNC_ATTENTION`

It does not automatically resume candidate queue processing if the operator invoked a vacancy-only refresh while the worker was paused.

## UI counters

For repeated daily sync, prefer counters that explain delta rather than total database size.

Suggested summary:

- `vacancies_discovered`
- `vacancies_created`
- `vacancies_updated`
- `vacancies_unchanged`
- `descriptions_recovered`
- `new_applications`
- `existing_applications`
- `new_resume_tasks`
- `already_covered`
- `attention_unchanged`

Example no-op daily run:

```text
Vacantes sin cambios: 47
Nuevas postulaciones: 0
CVs nuevos: 0
Ya cubiertos: 161
```

## Data model strategy

Prefer existing tables and durable cursor patterns.

Reuse where possible:

- candidate ingestion cursors for Gmail;
- `CandidateIngestionEvent` external IDs;
- `IndeedCandidateLink.staged_at`;
- `IndeedEmailResumeTask` terminal/active statuses;
- `IndeedJobLink.discovery_key` for stable vacancy identity;
- job description source fields introduced by migration 014.

A new migration is justified only for durable incremental state that cannot be expressed safely with existing cursors/links, such as a one-time candidate-reconciliation watermark or vacancy snapshot fingerprint.

Do not introduce a second candidate queue or a new vacancy table.

## Failure semantics

- Incremental sync failure must not reset Gmail history to zero.
- A failed vacancy scrape must not erase descriptions.
- One malformed vacancy/candidate does not abort unrelated items.
- Repeating the same provider payload is idempotent.
- A completed CV is not redownloaded without newer application/resume evidence.
- Historical attention does not silently become pending work on every sync.
- Global auth challenge pauses browser-dependent processing without corrupting cursors.

## Testing requirements

### Incremental backend

Cover:

- second sync with no Gmail changes creates no candidate work;
- one new Gmail application reconciles only the affected candidate/job;
- first bootstrap does not owner-scan all links once per page;
- historical ambiguity is not requeued by normal incremental sync;
- explicit Retry attention still requeues attention;
- same candidate/newer same-job application is recognized as new versioned work;
- same candidate/different job remains independent;
- completed canonical resume remains covered when nothing changed;
- one-time backlog reconciliation runs once and persists completion.

### Vacancy sync

Cover:

- stable vacancy identity is required;
- non-empty description is required for automatic new vacancy creation;
- repeated identical snapshot is unchanged/idempotent;
- changed Indeed description updates `indeed_description`;
- active AI description survives provider refresh;
- empty scrape cannot erase stored description;
- historical title-only vacancy can be adopted only when match is unambiguous.

### Desktop agent

Cover:

- `Sincronizar todo` runs vacancy phase before application phase;
- `Actualizar vacantes` never calls Gmail sync;
- vacancy-only action never claims candidate tasks;
- conflicting browser actions are serialized;
- no-op incremental run reports zero new candidate work;
- candidate-level review continues queue processing;
- auth challenge globally pauses.

## Acceptance criteria

1. A second `Sincronizar todo` with no new Indeed/Gmail changes does not reopen previously completed candidates.
2. Normal incremental sync does not scan every historical candidate/job pair on every page.
3. Historical `INDEED_CANDIDATE_AMBIGUOUS` tasks remain attention-only unless explicitly retried or new evidence arrives.
4. A genuinely new application creates/processes only the required delta.
5. `Actualizar vacantes` refreshes vacancies/descriptions without Gmail or candidate processing.
6. Vacancy refresh preserves AI descriptions and recruiter source selection.
7. No concurrent Resume Agent command drives the same Chrome/CDP session.
8. Repeating either action is idempotent.
9. Existing duplicate semantics from PR #82 remain intact.
10. No change is merged to `main` as part of this branch work without explicit user approval.

## Out of scope

- automatic periodic scheduling;
- deletion of local vacancies missing from one Indeed page;
- changing Gmail provider integration architecture;
- replacing Browser Use/CDP with the official Indeed API;
- automatic full reprocessing of every historical candidate;
- merging this feature branch into `main` without explicit approval.
