# Indeed Candidates + Disposition Sync Design

## Goal

Extend the existing Indeed Job Sync integration so Asiati Talent can retrieve Indeed candidate assets into the existing candidate/evaluation/ranking pipeline, track application status locally, and sync dispositions back to Indeed. The implementation must remain testable without a live Indeed account and disabled by default in production.

## Current Indeed constraints

- Retrieve Candidates uses GraphQL `atsSyncCandidateSync.fetchAssets` with a 2-legged OAuth token.
- Passing the previous `fetchAssets` token acknowledges that batch; acknowledged assets can later be recovered with `assetsByTimeRange`.
- Retrieve Candidates currently exposes Interested Candidate assets and can add new asset types later, so unknown asset types must be ignored safely rather than crashing a whole batch.
- Candidate source attribution and resume data must be preserved.
- Disposition Sync uses `partnerDisposition.send`.
- Indeed requires at least one `NEW` disposition for Indeed-sourced applications where Disposition Sync applies.
- Dispositions must be sorted oldest-first and sent in batches of at most 25.
- A disposition identifier must use exactly one of Indeed Apply ID, ITTK, Universal Apply ID, or an alternate identifier.
- Alternate identifiers can use `EmployerJob.id` plus candidate email when standard application identifiers are unavailable.

## Architecture

Keep `app/domains/indeed` as the provider adapter. Do not build a separate candidate model for Indeed.

Flow:

1. Indeed `fetchAssets` returns a batch.
2. Each supported asset is mapped into a provider-neutral candidate ingestion DTO.
3. Candidate identity resolution reuses the existing email/phone identity rules.
4. Candidate is created/reused, attached idempotently to the matching local Job, and an `IndeedCandidateLink` is persisted.
5. Source attribution and provider metadata are stored on the link, not in core Candidate columns.
6. Candidate ingestion creates an initial local application state `APPLIED` and queues a `NEW` disposition when a usable disposition identifier exists.
7. Later local application status changes create durable disposition events.
8. `sync_dispositions` sends pending events oldest-first in batches of 25 and records success/failure.

No scheduler is required in this phase. Manual sync endpoints and frontend controls invoke the services. A future cron/EventBridge job can call the same service.

## Local application state

Extend `JobCandidate` with provider-neutral ATS state:

- `application_status` text, default `APPLIED`.
- `status_changed_at` timezone-aware datetime.

Supported V1 local states:

- `APPLIED`
- `SCREENING`
- `INTERVIEW`
- `OFFER`
- `HIRED`
- `REJECTED`
- `WITHDRAWN`
- `ON_HOLD`

Indeed mapping:

- `APPLIED` -> `NEW`
- `SCREENING` -> `POSITIVELY_SCREENED`
- `INTERVIEW` -> `INTERVIEW`
- `OFFER` -> `OFFER_MADE`
- `HIRED` -> `HIRED`
- `REJECTED` -> `NOT_SELECTED`
- `WITHDRAWN` -> `WITHDRAWN`
- `ON_HOLD` -> no outbound disposition until a supported terminal/progress status is selected.

The mapping lives exclusively in the Indeed adapter.

## Persistence

### `indeed_candidate_links`

- `id` UUID PK
- `owner_sub` text not null
- `candidate_id` FK candidates.id cascade delete
- `job_id` FK jobs.id cascade delete
- `asset_id` text not null
- `registration_id` text nullable
- `employer_identifier` text nullable
- `source_enum_key` text nullable
- `source_name` text nullable
- `sourced_posting_id` text nullable
- `indeed_apply_id` text nullable
- `ittk` text nullable
- `universal_apply_id` text nullable
- `resume_name` text nullable
- `resume_url` text nullable
- `staged_test` boolean not null default false
- `acknowledged_at` timestamp nullable
- `created_at`, `updated_at`

Constraints:

- unique `(owner_sub, asset_id)` for idempotency.
- index `(owner_sub, job_id)`.
- Candidate remains provider-neutral.

### `indeed_candidate_sync_state`

One row per owner:

- `id` UUID PK
- `owner_sub` unique not null
- `ack_token` text nullable
- `last_fetch_at` timestamp nullable
- `last_ack_at` timestamp nullable
- `last_error` text nullable
- `created_at`, `updated_at`

Important acknowledgment rule: persist/process every asset successfully first; only persist/use the next acknowledgment token after the batch transaction succeeds. Never acknowledge a failed batch.

### `indeed_disposition_events`

- `id` UUID PK
- `owner_sub` text not null
- `candidate_link_id` FK indeed_candidate_links.id cascade delete
- `local_status` text not null
- `indeed_status` text not null
- `status_changed_at` timestamp not null
- `sync_status` text not null: `PENDING`, `SENT`, `FAILED`
- `attempt_count` int not null default 0
- `last_error` text nullable
- `sent_at` timestamp nullable
- `created_at`

Idempotency constraint: unique `(candidate_link_id, local_status, status_changed_at)`.

## Job matching

For an asset containing `contact.job.sourcedPostingId`, resolve the local job through `IndeedJobLink.sourced_posting_id`. If no match exists, record the asset as skipped in the sync result and do not create an unassigned candidate.

This keeps candidate imports job-scoped and prevents accidental tenant/job leakage.

## Candidate identity and metadata

Reuse existing owner-scoped identity semantics for email and phone. Retrieve Candidates provides a remote resume URL rather than a manually staged S3 upload. In this phase:

- preserve `resume_name` and `resume_url` on the Indeed candidate link;
- expose them to the recruiter UI;
- do not pretend the remote resume is an ImportItem;
- leave physical resume download/storage to a follow-up hardened document-ingestion task if required for Bedrock evaluation.

This prevents mixing manual upload semantics with provider assets.

## Retrieve Candidates GraphQL

Add `fetch_assets(limit=25)` service using the existing `IndeedClient`.

GraphQL requests candidate:

- asset id
- metadata stagedAt/stagedTest/employerIdentifier/source attribution
- candidate name/email/location/phone
- resume PDF name/url
- sourcedPostingId
- recruiterEmail

Unknown asset types are reported as skipped.

Manual endpoint:

`POST /api/integrations/indeed/candidates/sync`

Response:

- `fetched`
- `created`
- `reused`
- `skipped`
- `next_token_present`
- `last_sync_at`

The endpoint performs one provider batch per request. This avoids long-running HTTP calls and makes future scheduling straightforward.

## Application status API

Add:

`PUT /api/jobs/{job_id}/candidates/{candidate_id}/status`

Body:

```json
{"status":"INTERVIEW"}
```

Rules:

- owner-scoped job and candidate relation required;
- status must be in the local enum set;
- update `JobCandidate.application_status` and `status_changed_at`;
- if an Indeed candidate link exists and the status maps to Indeed, create a durable disposition event;
- do not synchronously call Indeed from the status-change request.

## Disposition identifier strategy

Build exactly one `identifiedBy` value in this priority order:

1. `indeedApplyID`
2. `ittk`
3. `universalApplyId`
4. alternate identifier using:
   - local job's `IndeedJobLink.employer_job_id`
   - candidate email

If none can be built, leave the event failed/not-sendable with a clear local error. Never fabricate provider IDs.

## Disposition Sync

Endpoint:

`POST /api/integrations/indeed/dispositions/sync`

Behavior:

- select pending/failed retryable events for owner;
- sort by `status_changed_at` ascending;
- process max 25 per provider request;
- call GraphQL `partnerDisposition.send`;
- mark successful events `SENT`;
- map returned failed dispositions to corresponding events and mark `FAILED` with rationale;
- increment attempts on every send attempt;
- no automatic infinite retry loop.

## Frontend Jobs UI

Extend `Jobs.jsx` minimally rather than building a new integration page.

Job form adds publication metadata needed by Indeed:

- country code
- city
- employment type
- public slug

Job cards/detail show an Indeed section:

- integration configured/disabled status
- published/not-published state
- sourced posting status when available
- buttons: Publish, Refresh status, Sync candidates, Expire

Candidate rows/details show source attribution when an Indeed link exists. Add a status selector only where candidate-job context exists; keep the change small and compatible with the future Kanban pipeline.

## Development/mock mode

No live Indeed account is required for CI. Tests inject fake/mock Indeed clients and deterministic asset/disposition responses.

`INDEED_ENABLED=false` remains the default. Real provider calls require enabled + configured credentials.

## Error handling

- disabled/unconfigured integration -> 503
- missing local job/candidate/link -> 404
- invalid local status -> 422
- provider/network/GraphQL failure -> 502 for direct manual sync calls
- a candidate batch must not be acknowledged if processing fails
- one unsupported asset must not crash supported assets in the same fetched batch
- disposition partial failures must preserve per-event results

## Security and privacy

- Never log OAuth secrets/tokens or full resume URLs.
- All persistence queries are owner-scoped.
- Candidate data from Indeed retains source attribution.
- No candidate is deleted when an Indeed registration/integration is disabled.
- No live provider calls occur in CI.

## Out of scope

- automatic EventBridge/cron scheduling
- full ATS Kanban pipeline UI
- interview/offer modules
- automatic physical download of Indeed resumes into S3
- production Partner Console onboarding/certification
- Indeed Apply button implementation

These can build on the interfaces in this design.