# Gmail Candidate Ingestion Setup

This document defines how candidate-ingestion Gmail credentials are configured and rotated without code changes.

## Authentication model

The application does **not** store or use the mailbox password. Gmail access uses Google OAuth 2.0 with the read-only Gmail scope and an offline refresh token. `GMAIL_USER_ID=me` means the API operates on the account that granted that token.

Never commit OAuth client secrets, refresh tokens, state secrets, mailbox passwords, or agent tokens to GitHub.

## Runtime source of truth

Production Gmail OAuth/runtime values live in AWS Secrets Manager under `/ai-recruiter/prod/gmail-oauth`. Environment variables remain useful for local development, but the production secret overlays the operational values.

For Indeed application notifications, the target runtime configuration **after the backend and local resume agent are deployed and verified** is:

```json
{
  "enabled": true,
  "query": "from:indeedemail.com",
  "allowed_senders": [],
  "ingestion_provider": "INDEED"
}
```

Do not add `has:attachment`: Indeed application emails in this flow contain a **resume link**, not the resume PDF itself. The Gmail `from:` query is only a mailbox-discovery restriction; the specialized Indeed parser independently validates the parsed sender domain and the resume-link host before creating a download task.

## Local development

A local test mailbox can still use environment-derived values. Keep the mailbox disabled until a restrictive sender query or sender allowlist is configured.

```text
GMAIL_ENABLED=false
GMAIL_USER_ID=me
GMAIL_QUERY=from:indeedemail.com
GMAIL_INGESTION_PROVIDER=INDEED
```

OAuth credentials belong in local secret storage or the configured Secrets Manager document, never in committed files.

## Reauthorizing another mailbox

To change the Gmail account used by the integration:

1. Authorize the replacement Google account with the approved Gmail read-only scope.
2. Complete the existing OAuth callback flow so the new refresh token is stored in Secrets Manager.
3. Confirm the connected mailbox identity from the integrations status endpoint/UI.
4. Keep ingestion disabled until the source filter is reviewed.
5. Run a controlled sync and one known application before processing backlog.

No mailbox password is required.

## Secret rotation

Issue and validate a replacement OAuth credential before revoking the old one. Replace secret material atomically, validate Gmail connectivity, then revoke the superseded credential. Never add a `GMAIL_PASSWORD` setting.

## Indeed resume bridge gate

Gmail ingestion must stay disabled until all of these are true:

- migration `011` and the backend agent endpoints are deployed;
- the machine credential exists in `/ai-recruiter/prod/indeed-resume-agent`;
- the raw machine token is provisioned only on the authorized Windows workstation;
- the Windows agent authenticates successfully and can read queue stats;
- one controlled application can be claimed, downloaded, uploaded, and handed to the existing candidate-ingestion worker;
- no credential value exists in the repository.

The detailed cutover and rollback sequence is in `docs/indeed-resume-agent-operations.md`.
