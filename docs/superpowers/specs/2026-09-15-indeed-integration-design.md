# Indeed Employers Integration Design

## Goal

Add a first-class Indeed Employers integration to the AI Recruiter / Asiati Talent backend, beginning with official Indeed Job Sync support and an integration foundation that can later support Retrieve Candidates and Disposition Sync without coupling Indeed-specific concepts into the core job or candidate domains.

## Scope

This first delivery includes:

- Indeed OAuth/client-credentials configuration.
- A resilient Indeed GraphQL client.
- Persistent Indeed connection and job-link state.
- Neutral job fields required for external publication.
- Publish/upsert job to Indeed.
- Query publication state.
- Expire an Indeed job explicitly.
- Sync event/audit records.
- Feature flagging so production can deploy before real Indeed credentials are available.
- Tests using mocked transports; no live Indeed calls in CI.

This delivery does not yet include Retrieve Candidates, Disposition Sync, Indeed Apply candidate ingestion, or frontend controls.

## Architectural principles

1. Indeed remains an external adapter. Core `Job` and `Candidate` entities must not depend on Indeed enums or IDs.
2. Job creation and editing must continue to succeed if Indeed is unavailable.
3. External operations are explicit under `/api/jobs/{job_id}/integrations/indeed/*`.
4. `sourcedPostingId` is persisted because Indeed requires it for later status checks and expiration.
5. Secrets are injected through environment/secret storage and are never committed.
6. `INDEED_ENABLED=false` is the default so the code can ship before partner credentials are ready.

## Domain structure

Create `app/domains/indeed/` with `client.py`, `schemas.py`, `mapper.py`, `repository.py`, `service.py`, `router.py`, `exceptions.py`, and `constants.py`.

## Neutral Job fields

Add neutral fields useful for Asiati careers and future job boards:

- `country_code: Text | null` (ISO 3166-1 alpha-2)
- `city: Text | null`
- `employment_type: Text | null`
- `public_slug: Text | null`
- `published_at: DateTime | null`

## Persistence

### `indeed_connections`

- `id` UUID PK
- `owner_sub` text unique not null
- `employer_id` text nullable
- `status` text not null (`DISCONNECTED`, `CONFIGURED`, `ERROR`)
- `last_error` text nullable
- `created_at`, `updated_at`

No access token is persisted.

### `indeed_job_links`

- `id` UUID PK
- `job_id` FK jobs.id unique cascade delete
- `owner_sub` text not null
- `sourced_posting_id` text nullable until publish succeeds
- `external_status` text nullable
- `last_synced_at` timestamp nullable
- `last_error` text nullable
- `created_at`, `updated_at`

### `indeed_sync_events`

- `id` UUID PK
- `owner_sub` text not null
- `job_id` FK jobs.id nullable set null on delete
- `operation` text not null (`PUBLISH`, `STATUS`, `EXPIRE`)
- `status` text not null (`PENDING`, `SUCCEEDED`, `FAILED`)
- `external_id` text nullable
- `error_code` text nullable
- `error_message` text nullable
- `created_at`, `completed_at`

## Configuration

- `INDEED_ENABLED=false`
- `INDEED_CLIENT_ID=`
- `INDEED_CLIENT_SECRET=`
- `INDEED_TOKEN_URL=https://apis.indeed.com/oauth/v2/tokens`
- `INDEED_GRAPHQL_URL=https://apis.indeed.com/graphql`
- `INDEED_REQUEST_TIMEOUT_SECONDS=10`
- `CAREERS_BASE_URL=https://www.asiaticorp.com/jobs`

## OAuth and GraphQL client

Use `httpx`, already a dependency. `IndeedClient` acquires client-credentials tokens, caches them in memory until shortly before expiry, executes GraphQL with Bearer auth, and distinguishes network, HTTP, top-level GraphQL, and operation-level failures. Secrets and bearer tokens are never logged. Tests inject a mocked transport/client.

## Job mapping

Required local publication data:

- title
- non-empty description
- country_code
- city
- local job UUID as stable source identifier
- public URL derived from `CAREERS_BASE_URL` and `public_slug` when present

Missing required fields fail locally before a network call. Employment type mapping is isolated and unknown values are omitted rather than guessed.

## API

- `GET /api/integrations/indeed/status`
- `POST /api/jobs/{job_id}/integrations/indeed/publish`
- `GET /api/jobs/{job_id}/integrations/indeed/status`
- `POST /api/jobs/{job_id}/integrations/indeed/expire`

All endpoints are owner-scoped by the existing Cognito `sub`.

## Failure semantics

- Local job missing or owned by another user: 404.
- Indeed disabled/not configured: 503.
- Missing publication fields: 422.
- Indeed auth, HTTP, GraphQL, or network failure: 502.
- Failed external publication never deletes or rolls back the local job.

## Testing strategy

Follow existing pytest patterns and TDD. Cover neutral job fields, mapper validation, deterministic payload construction, OAuth token caching, auth headers, GraphQL error handling, publish success/failure persistence, status/expire prerequisites, owner isolation, disabled/config-missing behavior, and router status codes. No live Indeed request is allowed in tests.

## Future phases

Retrieve Candidates will add `indeed_candidate_links` and feed the existing candidate import pipeline. Disposition Sync will map local pipeline states in a dedicated mapper and batch/retry provider updates asynchronously.

## Deployment

Deploy safely with `INDEED_ENABLED=false`. Once credentials are issued, inject them through production secrets/environment and flip the flag; no code change is required.
