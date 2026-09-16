# Gmail Candidate Ingestion Setup

This document defines how candidate-ingestion Gmail credentials are configured and rotated without code changes.

## Authentication model

The application does **not** store or use the mailbox password.

Gmail access uses Google OAuth 2.0 with offline access:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

The short-lived access token is obtained at runtime from Google's token endpoint.

`GMAIL_USER_ID=me` means the Gmail API operates on whichever Google account granted the refresh token. This lets us switch mailboxes by reauthorizing another account instead of changing code.

## Current development account

Until the Asiati corporate mailbox is available, development may use a personal Gmail account authorized against the development Google Cloud OAuth client.

Do not commit real values to GitHub. Local values belong in `.env`, which is ignored by git.

Recommended development configuration:

```text
GMAIL_ENABLED=true
GMAIL_CLIENT_ID=<development oauth client id>
GMAIL_CLIENT_SECRET=<development oauth client secret>
GMAIL_REFRESH_TOKEN=<personal gmail refresh token>
GMAIL_USER_ID=me
GMAIL_QUERY=has:attachment
GMAIL_ALLOWED_SENDERS=<optional comma-separated sender allowlist>
```

## Switching to the corporate mailbox

When the corporate mailbox is ready:

1. Authorize the corporate Google account with the same approved Gmail read-only scope.
2. Obtain a new refresh token for that account.
3. Replace the Gmail OAuth secret values in the target environment.
4. Keep `GMAIL_USER_ID=me` unless there is a specific reason to address another mailbox explicitly.
5. Run a mailbox connectivity smoke test.
6. Verify one known test application is ingested idempotently.

No application-code change should be required for this mailbox swap.

## Secret rotation

If OAuth credentials need rotation:

- issue/re-authorize the replacement credential first;
- validate it against Gmail;
- replace the secret atomically in the runtime environment;
- revoke the old refresh token/client credential after successful verification.

Never add a `GMAIL_PASSWORD` variable or persist a human mailbox password.

## AWS GATE

Do **not** provision production Gmail secrets or continuous mailbox polling in AWS during early local/CI development.

The project is ready for the AWS Gmail deployment step only when all of the following are true:

- Gmail OAuth transport tests are green;
- Candidate Ingestion Core persistence and migration `007` are green;
- a normalized Gmail message can create an idempotent ingestion event;
- PDF/DOCX attachments are written to the source/staging S3 path;
- the `candidate_ingestion` SQS message contract is green;
- the worker can resume and process an event safely;
- ambiguous job resolution becomes `NEEDS_REVIEW` instead of guessing;
- no credentials are committed to the repository.

At that point the next infrastructure step is:

1. store Gmail OAuth secrets in AWS Secrets Manager;
2. grant the runtime role permission only to that Gmail secret;
3. configure the worker/poller environment from the secret;
4. provision the continuous mailbox polling schedule/service;
5. validate end-to-end with a test email before enabling the corporate mailbox.
