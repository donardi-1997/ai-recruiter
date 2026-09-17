# Indeed Email Resume Agent Bridge — Design

Date: 2026-09-17

## Goal

Provide a temporary, production-usable bridge for Indeed applicants while waiting for the official Indeed integration approval. The bridge must support batches of hundreds of applicants, avoid storing Indeed credentials in AWS, preserve idempotency and resume progress after failures, and feed the existing Candidate Ingestion Core so the downstream candidate analysis and ranking pipeline does not need to change later.

## Scope

This design covers:

- Gmail detection of Indeed application emails.
- Extraction of candidate name, job title and the Indeed "Ver CV" link from message bodies.
- Deterministic job resolution.
- Durable queueing of resume-download work.
- A Windows desktop agent using Playwright and a persistent local browser profile.
- Safe resume download and upload into the existing candidate-ingestion storage path.
- Retry, lease, restart and human-intervention behavior.
- Security boundaries for the local agent.
- Testing strategy and rollout.

This design does not automate MFA or CAPTCHA, does not store an Indeed password, and does not replace the future official Indeed API integration.

## Existing System Constraints

The current candidate-ingestion domain already provides provider-neutral durable events and documents through `CandidateIngestionEvent`, `CandidateIngestionDocument` and `CandidateIngestionCursor`.

The current Gmail path:

1. Connects to Gmail through OAuth.
2. Performs full and incremental mailbox sync.
3. Fetches messages with Gmail `format=full`.
4. Normalizes supported PDF/DOCX attachments.
5. Marks messages with no supported attachment as `NEEDS_REVIEW` with `RESUME_ATTACHMENT_MISSING`.

The current generic email parser intentionally ignores message body content. That contract should remain unchanged. Indeed-specific HTML/plain-text extraction belongs in a separate adapter.

## High-Level Architecture

```text
Gmail mailbox
    |
    v
Gmail sync
    |
    v
Indeed email detector/parser
    |
    +--> resolve job safely
    |
    v
IndeedResumeTask queue
    |
    v
Windows Resume Agent
    |
    v
Visible Playwright browser with dedicated persistent profile
    |
    v
Indeed "Ver CV" page
    |
    v
PDF download
    |
    v
Authenticated upload to AI Recruiter
    |
    v
Candidate Ingestion Core
    |
    v
Existing processing / evaluation / ranking
```

When the official Indeed API becomes available, only the source of the PDF changes:

```text
Today:      Gmail -> local browser agent -> PDF -> Candidate Ingestion Core
Future:     Indeed API              -> PDF -> Candidate Ingestion Core
```

## Design Choice

The selected approach is a local Windows agent with Playwright using a dedicated persistent browser profile.

Reasons:

- No Indeed password needs to be stored in AWS.
- The browser runs from a normal user workstation rather than a headless cloud environment.
- Login, MFA and CAPTCHA can be handled manually by the recruiter when Indeed requests them.
- The browser can reuse a local authenticated session.
- The workflow is deterministic enough that an LLM browser agent is unnecessary.

Alternatives rejected for the MVP:

- Headless Chromium in AWS: more fragile around session expiry, MFA and anti-bot checks.
- Browser extension: viable but more implementation overhead than needed for the temporary bridge.
- LLM/browser-use agent: unnecessary token cost and lower determinism for a fixed click/download/upload workflow.

## Gmail Detection and Parsing

### Gmail query

The existing query `has:attachment` is not sufficient because Indeed emails contain a link to the resume rather than the PDF itself.

The production query should be narrowed to Indeed-originated messages and should be paired with validation in code. The exact Gmail query remains configurable so operations can adjust it without code changes.

### Parser boundary

Add an Indeed-specific parser, for example:

`app/integrations/email_ingestion/indeed_email_parser.py`

It consumes a raw Gmail `format=full` message and returns a normalized Indeed application payload.

Expected fields:

```text
message_id
thread_id
sender
subject
candidate_name
job_title
resume_url
received_at
```

### Sender validation

The sender address must belong to the configured Indeed email domain, initially `@indeedemail.com`.

The parser must not trust display names.

### Resume-link validation

The parser may locate the anchor labelled or semantically equivalent to "Ver CV", but the resulting URL must pass all of these checks:

- HTTPS only.
- Hostname present.
- Hostname belongs to the configured Indeed host allowlist.
- No arbitrary third-party destination is accepted.

A message that looks like Indeed but contains an invalid external link becomes `NEEDS_REVIEW` rather than a downloadable task.

### Body decoding

The parser must support:

- `text/html`.
- `text/plain` fallback.
- Base64url-encoded Gmail body parts.
- Nested multipart MIME structures.

The existing generic email parser stays unchanged.

## Job Resolution

Job resolution remains deterministic and tenant-scoped.

Resolution order:

1. Explicit owned `job_id`, when supplied by an internal workflow.
2. One exact normalized match against extracted `job_title`.
3. One unambiguous normalized title match in the email subject.
4. Otherwise, no automatic job assignment.

If there are zero matches or multiple matches, the event/task is flagged for review. The system must never guess between two plausible vacancies.

A resume may still be downloaded and stored even when the job is ambiguous. Evaluation/ranking against a vacancy waits until a human resolves the job.

## Durable Queue Model

Add a specialized table, conceptually `indeed_email_resume_tasks`, linked one-to-one with the source `CandidateIngestionEvent`.

Suggested fields:

```text
id
owner_sub
ingestion_event_id
job_id nullable
candidate_name
job_title
status
lease_token nullable
lease_expires_at nullable
claimed_at nullable
attempt_count
last_error_code nullable
last_error_message nullable
completed_at nullable
created_at
updated_at
```

`ingestion_event_id` must be unique so repeated Gmail synchronization cannot create duplicate resume tasks for the same source event.

The source event continues to use the existing provider-neutral uniqueness rules, so mailbox re-sync remains idempotent.

## Task States

Primary states:

```text
WAITING_DOWNLOAD
CLAIMED
UPLOADED
COMPLETED
NEEDS_HUMAN
RETRY
FAILED
```

Typical successful transition:

```text
WAITING_DOWNLOAD -> CLAIMED -> UPLOADED -> COMPLETED
```

Human intervention:

```text
CLAIMED -> NEEDS_HUMAN -> WAITING_DOWNLOAD/CLAIMED -> ...
```

Transient failure:

```text
CLAIMED -> RETRY -> WAITING_DOWNLOAD
```

Permanent failure after retry limit:

```text
CLAIMED -> RETRY -> ... -> FAILED
```

## Lease and Recovery Semantics

The agent claims one task at a time.

Each claim creates:

- A random `lease_token`.
- `claimed_at`.
- `lease_expires_at`, initially about 10 minutes in the future.

Only the holder of the active lease token may heartbeat, upload or complete the task.

If the workstation crashes or loses power, an expired lease makes the task claimable again. Completed tasks are never replayed automatically.

The agent may send a heartbeat while a browser operation is active to extend the lease.

## Batch Behavior for 200+ Applicants

Gmail discovery and resume retrieval are intentionally decoupled.

Example first sync:

```text
Messages discovered:          200
New Indeed tasks:             194
Already known:                  3
Ambiguous job:                  2
Unrecognized Indeed message:    1
```

The local agent processes one Indeed browser task at a time. It does not open 200 tabs.

Example operational state:

```text
Total:             200
Completed:          73
Processing:          1
Waiting:           122
Needs human:         2
Failed:              2
```

If the machine stops on task 83, tasks 1-82 remain complete. Task 83 becomes available again after its lease expires. Processing resumes from unfinished work only.

The Indeed browser stage starts with concurrency 1. Higher concurrency is not enabled until real-world testing shows it is safe for the account and session.

Downstream AWS processing may continue in parallel as resumes arrive.

## Agent API

The local agent gets a purpose-specific API surface separate from ordinary user JWT routes.

Proposed endpoints:

```text
POST /api/agents/indeed-resume/claim
POST /api/agents/indeed-resume/{task_id}/heartbeat
POST /api/agents/indeed-resume/{task_id}/resume
POST /api/agents/indeed-resume/{task_id}/needs-human
POST /api/agents/indeed-resume/{task_id}/fail
GET  /api/agents/indeed-resume/stats
```

### Claim

`claim` returns at most one task for the MVP.

Example response:

```json
{
  "task_id": "...",
  "candidate_name": "WENDY KARINA MARQUEZ PRIETO",
  "job_title": "Analista de Automatizacion e IA",
  "resume_url": "https://...",
  "lease_token": "...",
  "lease_expires_at": "..."
}
```

The resume URL should be resolved from Gmail only when needed and should not be exposed more broadly than necessary.

## Agent Authentication

The agent must not reuse Katherine's personal Cognito/JWT token.

Create a dedicated machine credential with access limited to the resume-agent endpoints.

AWS secret location:

`/ai-recruiter/prod/indeed-resume-agent`

The corresponding workstation secret should be stored using Windows Credential Manager, not in source code, a batch file or a plaintext `.env` file.

The server stores a hashed or otherwise safely verifiable representation where appropriate, and the agent receives only the credential it needs.

The agent credential cannot access general candidates, jobs, users or administrative endpoints.

## Windows Agent

Implementation target for the MVP:

- Python.
- Playwright.
- Visible browser window.
- Packaged later as a Windows `.exe`.
- Manual start first; Windows auto-start can be added after stability is proven.

### Dedicated browser profile

Do not automate Katherine's normal browser profile directly.

Use a dedicated persistent profile such as:

`%LOCALAPPDATA%\ASIATI\ResumeAgent\browser-profile`

On first use, the agent opens Indeed in the visible browser and Katherine signs in manually. Session cookies remain local to that profile.

The application never asks for, receives or stores the Indeed password.

### Agent loop

```text
claim task
  -> open resume URL
  -> wait for page/download
  -> download PDF
  -> validate locally
  -> upload with lease token
  -> mark complete
  -> claim next task
```

Only one resume task is active at a time in the MVP.

## Human Intervention

If the browser detects a login screen, MFA challenge, CAPTCHA or another state requiring human input:

1. The task becomes `NEEDS_HUMAN`.
2. The visible browser remains available.
3. The UI indicates that Indeed requires intervention.
4. Katherine completes the interaction manually.
5. She resumes the agent.
6. The task is reclaimed or continued under a fresh valid lease.

The agent must not attempt to bypass CAPTCHA or automate MFA.

## Resume Upload and Validation

The uploaded file feeds the existing Candidate Ingestion Core.

Server-side checks:

- Maximum size: 15 MB to match the existing email-ingestion limit.
- PDF content type.
- PDF magic bytes begin with `%PDF-`.
- SHA-256 computed server-side.
- Valid task.
- Valid, non-expired lease token.
- Idempotent upload behavior.

After validation:

1. Store the source document using the existing ingestion storage abstraction.
2. Create or reuse a `CandidateIngestionDocument`.
3. Associate it with the original `CandidateIngestionEvent`.
4. Clear source-event missing-attachment errors where applicable.
5. Move the event/task into the normal downstream ingestion path.

Do not introduce a second candidate-processing pipeline.

## Retry Policy

Transient technical failures use bounded retries.

Initial policy:

```text
Attempt 1 -> retry
Attempt 2 -> retry
Attempt 3 -> FAILED
```

Backoff should be applied between retries rather than hammering Indeed.

Authentication, MFA and CAPTCHA are not counted as ordinary technical download failures; those become `NEEDS_HUMAN`.

A failed task never blocks the rest of the queue.

## Operational UI

The local agent should provide a minimal status window for the MVP:

```text
ASIATI Resume Agent

Indeed session: Active

Pending:          117
Downloading:        1
Completed:          79
Needs attention:     3
Failed:              0

[Pause] [Resume] [Open Indeed]
```

The first version may be simple, but queue status and human-intervention state must be visible.

## Security Requirements

- Never store an Indeed password in AWS or the application database.
- Never commit agent credentials to Git.
- Never expose Gmail OAuth client secrets to the browser agent.
- Validate the sender domain from the parsed email address, not the display name.
- Validate the resume URL against an explicit Indeed hostname allowlist.
- Validate the PDF on the server even if it was already checked locally.
- Use short-lived leases to prevent stale agents from completing reassigned work.
- Use a dedicated agent credential with least privilege.
- Keep the browser profile local to the authorized workstation.
- Do not automate CAPTCHA or MFA.

## Testing Strategy

Implementation follows TDD.

### Indeed email parser

- Realistic Indeed HTML email produces candidate name, job title and resume URL.
- Base64url Gmail MIME body decodes correctly.
- Nested multipart messages are supported.
- Non-Indeed sender is rejected.
- External "Ver CV" URL is rejected.
- Missing resume link becomes reviewable, not downloadable.

### Job resolution

- Exact unique normalized job title resolves.
- Unique subject match resolves.
- No match returns unresolved.
- Multiple matches return unresolved.
- Cross-tenant job cannot resolve.

### Queue and leases

- Up to 200 discovered messages produce at most 200 unique tasks.
- Running the same sync again creates no duplicates.
- Two agents cannot claim the same active task.
- Expired leases become claimable again.
- Heartbeat extends a valid lease.
- Stale lease tokens cannot upload or complete.
- Restart after task 83 does not replay completed tasks 1-82.

### Upload

- Valid PDF is stored in the Candidate Ingestion Core.
- Fake `.pdf` without `%PDF-` is rejected.
- File over 15 MB is rejected.
- Repeated upload is idempotent.
- Uploaded document preserves SHA-256 and source-event linkage.

### Windows agent

- Claim -> download -> upload -> complete.
- Login/MFA/CAPTCHA detection -> `NEEDS_HUMAN`.
- Transient failure -> retry.
- Retry limit -> `FAILED`.
- Browser profile persists across process restarts.

All browser behavior is mocked or simulated in CI. CI must not log in to Indeed.

## Rollout Plan

1. Unit and integration tests green in CI.
2. Deploy backend schema and endpoints.
3. Configure dedicated agent credential.
4. Package or run the Windows agent on Katherine's workstation.
5. First-run manual Indeed login in the dedicated browser profile.
6. Smoke test with one real application.
7. Test a batch of 5-10 applications.
8. Observe timings, session behavior and failure modes.
9. Enable the larger backlog only after the small batch is stable.
10. Keep concurrency at 1 initially.

## Success Criteria

The bridge is successful when:

- A real Indeed email in Gmail produces exactly one durable task.
- The agent can retrieve the resume using the local authenticated Indeed session.
- The PDF is stored through the existing Candidate Ingestion Core.
- The candidate reaches the existing analysis/ranking pipeline without a separate processing path.
- Duplicate Gmail syncs do not duplicate tasks or candidates.
- Power loss or agent restart does not lose completed work.
- Login/MFA/CAPTCHA pauses only the affected task and does not corrupt the queue.
- A backlog on the order of 200 resumes can be processed unattended except for explicit human-intervention states.

## Deferred Work

Not part of the MVP:

- Multiple concurrent Indeed browser workers.
- Automatic Windows startup/service behavior.
- Browser extension implementation.
- Cloud-hosted browser worker.
- Automated MFA or CAPTCHA handling.
- Removal of the bridge after official Indeed API integration is enabled.

The future official Indeed integration should reuse the same Candidate Ingestion Core and retire only the Gmail/body-parser/local-browser retrieval layer.