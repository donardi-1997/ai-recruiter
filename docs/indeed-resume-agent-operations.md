# Indeed Resume Agent Operations

This runbook covers the controlled production cutover for Indeed application emails whose CV is exposed through a temporary **Ver CV** link rather than a Gmail attachment.

## Security model

The backend stores durable task state, but it never persists the temporary Indeed resume URL. A claim re-fetches the original Gmail message, validates the Indeed sender/link again, and returns the current URL only to the authenticated local agent.

The Windows agent authenticates with `X-ASIATI-Agent-Token`. Production stores only the SHA-256 digest of that token in AWS Secrets Manager. The raw token belongs only in Windows Credential Manager on the authorized workstation; do not place it in source code, `.env` files, logs, screenshots, tickets, or chat.

Secret contract for `/ai-recruiter/prod/indeed-resume-agent`:

```json
{
  "enabled": true,
  "owner_sub": "<Cognito owner sub>",
  "token_sha256": "<64 lowercase hex characters>"
}
```

## Required cutover order

1. Deploy migration `011` and the backend containing the Indeed resume-agent API. Do not enable Gmail discovery yet.
2. Create `/ai-recruiter/prod/indeed-resume-agent` with `enabled`, the correct Cognito `owner_sub`, and only the SHA-256 digest of the generated machine token.
3. Provision the **raw** machine token into Windows Credential Manager on Katherine's authorized PC. Do not copy the raw token into AWS or GitHub.
4. Install/start the Windows resume agent. Verify machine authentication and `GET /api/agents/indeed-resume/stats` before processing any application.
5. Update `/ai-recruiter/prod/gmail-oauth` operational fields to:

```json
{
  "enabled": true,
  "query": "from:indeedemail.com",
  "allowed_senders": [],
  "ingestion_provider": "INDEED"
}
```

Preserve all existing OAuth/client/refresh/state fields when updating that secret.
6. Run one Gmail sync. Confirm the recognized Indeed notification creates one durable `WAITING_DOWNLOAD` task and does not store a resume URL.
7. Smoke-test **one real application** end to end: claim → browser/session download → PDF upload → task `COMPLETED` → candidate-ingestion queue handoff.
8. Process a controlled batch of **5–10** applications. Check completed/retry/needs-human/failed counts and confirm no duplicate candidate ingestion.
9. Only after that batch is clean, allow the larger backlog to process.

## Expected operational states

`WAITING_DOWNLOAD` is ready for the agent. `CLAIMED` has an active 10-minute lease. `RETRY` becomes eligible after its backoff. `NEEDS_HUMAN` is intentionally excluded until explicitly resumed. `FAILED` and `COMPLETED` are terminal. An expired `CLAIMED` task is reclaimable, so a workstation restart does not require deleting or recreating earlier work.

A successful PDF upload sets the ingestion event to `STORED` and leaves `queue_dispatched_at` empty. The existing candidate-ingestion repair cycle then sends that event to the shared worker; the local agent must not call Bedrock, evaluation, or ranking directly.

## Rollback

If the bridge misbehaves:

1. Set only the Gmail operational field `enabled=false` in `/ai-recruiter/prod/gmail-oauth`, preserving the rest of the JSON document.
2. Stop the Windows resume agent.
3. Leave durable events/tasks/documents untouched for diagnosis and later recovery.

No candidate data deletion is required. Existing completed tasks remain terminal; pending/retry tasks can resume after the fault is corrected.

## Failure handling

A stale or wrong lease must receive `409`. Invalid/missing PDF content is rejected before storage. Invalid Indeed sender/link data moves work to safe review states without persisting the rejected URL. Authentication failures return no secret/hash material. Repeated upload of the same PDF is idempotent by SHA-256; a different document for the same event is a conflict rather than an overwrite.
