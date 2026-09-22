# Candidate Lifecycle Design

## Goal

Add a non-destructive four-month lifecycle for candidates, measured from the candidate's latest application date, while preserving historical CVs, evaluations, vacancy associations and recruiter traceability.

## Business rule

A candidate is active while their most recent application is less than four calendar months old.

The lifecycle anchor is the latest known application timestamp across all vacancies for the canonical candidate. A later application to the same or another vacancy resets the lifecycle clock.

When four calendar months have elapsed since that latest application, the candidate becomes archived/inactive by lifecycle policy. The candidate is not deleted.

## States

Use two effective lifecycle states for this delivery:

- `ACTIVE`: latest application is within the four-month window, or the candidate has no reliable application timestamp and therefore must not be archived automatically.
- `ARCHIVED`: latest application is at least four calendar months old.

Do not create a destructive `EXPIRED` deletion state. `ARCHIVED` is reversible.

## Source of the lifecycle timestamp

The preferred timestamp is the newest application timestamp associated with the canonical candidate, using provider/application evidence already available in the ingestion domain, including `IndeedCandidateLink.staged_at` when present and durable candidate-ingestion event timestamps as a fallback when they represent an actual application.

Do not use candidate creation date as the lifecycle anchor.

Do not infer a newer application from candidate name alone.

## Reactivation

Any genuinely newer application for the canonical candidate immediately makes the effective lifecycle state `ACTIVE` again and restarts the four-month window from that application.

Reactivation must work whether the new application is to the same vacancy or a different vacancy.

## Visibility

The Candidates view should default to `ACTIVE` candidates.

Provide filters:

- `Activos`
- `Archivados`
- `Todos`

Pagination remains server-side and fixed at 20 candidates per page for every lifecycle filter.

Changing lifecycle filter resets the candidate list to page 1.

## Data model strategy

Prefer deriving lifecycle from durable application timestamps rather than storing a mutable status that can drift from reality.

A persisted lifecycle field is justified only if query performance requires it and there is a reliable update/backfill mechanism. If persisted, it is cache/materialized state, not the source of truth; latest application timestamp remains authoritative.

Expose lifecycle metadata in candidate list payloads:

- `lifecycle_status`
- `latest_application_at`
- `archive_at` when derivable

## Four-month semantics

Use four calendar months, not a hard-coded 120-day approximation. For example, an application on May 31 archives on September 30 under normal calendar-month clamping semantics.

All comparisons must be timezone-aware and performed against UTC instants after provider timestamps are normalized.

## Safety rules

- Never delete a candidate automatically at four months.
- Never delete or detach CVs, evaluations or vacancy history when archiving.
- A candidate without a reliable application timestamp stays `ACTIVE` and can be surfaced for data-quality review later.
- A newer application always overrides prior archival state.
- The lifecycle job/query must be owner-scoped.
- Duplicate application semantics from PR #82 remain unchanged.

## Candidate list API

The paginated candidates endpoint should support lifecycle filtering, for example:

`GET /api/candidates?page=1&page_size=20&lifecycle=active`

Response shape:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

Each candidate item exposes lifecycle metadata through the presenter.

Allowed lifecycle filters:

- `active`
- `archived`
- `all`

Default: `active`.

## Acceptance criteria

1. Candidate pagination is fixed at 20 records per page.
2. Candidates are active for four calendar months from their latest application.
3. A later application resets the clock and reactivates an archived candidate.
4. Candidates are archived, never automatically deleted.
5. Active candidates are the default Candidates view.
6. Recruiters can switch between active, archived and all candidates.
7. Candidates with no reliable application date are not auto-archived.
8. Lifecycle filtering and pagination are owner-scoped and server-side.
9. CVs, evaluations and vacancy history remain available after archival.
10. Nothing from this branch is merged to `main` without explicit user approval.

## Out of scope

- hard deletion at lifecycle expiry;
- configurable retention periods per recruiter;
- automated email notifications before archival;
- scheduled physical deletion of documents;
- using candidate creation date as a substitute for application date.
