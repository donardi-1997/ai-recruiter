# Indeed Email Resume Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the server-side half of the temporary Indeed bridge: detect Indeed application emails in Gmail, create durable resume-download tasks, expose a least-privilege machine API with leasing, accept validated PDF uploads from the Windows agent, and hand those PDFs into the existing Candidate Ingestion Core without creating a parallel candidate-processing pipeline.

**Architecture:** Keep the generic Gmail attachment parser unchanged. Add an Indeed-specific MIME/body parser and a one-to-one `IndeedEmailResumeTask` linked to the existing `CandidateIngestionEvent`. Gmail discovery creates/reuses events and download tasks. A dedicated machine-authenticated API claims one task at a time with a 10-minute lease. Resume URLs are resolved from Gmail only at claim time and are not persisted. Valid PDF uploads create/reuse `CandidateIngestionDocument`, move the source event to `STORED`, and rely on the existing candidate-ingestion repair/worker path for S3/Bedrock/evaluation/ranking.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, Gmail REST API, AWS Secrets Manager, S3, existing SQS/Bedrock candidate-ingestion worker, pytest.

**Spec:** `docs/superpowers/specs/2026-09-17-indeed-email-resume-agent-design.md`

## Global Constraints

- Alembic head is currently `010`; this feature uses migration `011` revising `010`.
- Do not change the provider-neutral `parse_gmail_message()` contract to start exposing email bodies.
- Do not store the Indeed password, browser cookies, Gmail OAuth secrets, or raw agent token in the database or repo.
- Do not persist the temporary Indeed `Ver CV` URL. Resolve it from Gmail when an agent successfully claims a task.
- Validate sender addresses and URL host boundaries in code even when Gmail query filtering is configured.
- Start with one browser worker per agent and one claimed task at a time.
- Lease duration is 600 seconds. Heartbeat renews the lease to `now + 600s`.
- Technical failures use at most 3 attempts. Attempt 1 retry delay: 15 seconds; attempt 2 retry delay: 60 seconds; attempt 3 becomes `FAILED`.
- Login, MFA and CAPTCHA are `NEEDS_HUMAN`; they are not counted as download failures.
- Resume upload accepts only `application/pdf`, maximum `15 * 1024 * 1024` bytes, and `%PDF-` magic bytes.
- TDD is mandatory for each behavior change. Every task below starts RED, then implements the smallest behavior needed to turn GREEN.
- Run existing Gmail, candidate-ingestion, Indeed-resume and migration tests after each subsystem change.

---

### Task 1: Add the Indeed application email parser

**Files:**
- Create: `app/integrations/email_ingestion/indeed_email_parser.py`
- Create: `app/tests/test_indeed_email_parser.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ParsedIndeedApplication:
    message_id: str
    thread_id: str | None
    sender: str
    subject: str
    candidate_name: str
    job_title: str
    resume_url: str
    internal_date_ms: int | None

class NotIndeedMessage(ValueError): ...
class InvalidIndeedMessage(ValueError): ...
class InvalidIndeedResumeLink(ValueError): ...

def parse_indeed_application_email(
    message: dict[str, Any],
    *,
    sender_domains: tuple[str, ...] = ("indeedemail.com",),
    resume_host_suffixes: tuple[str, ...] = ("indeed.com", "indeedemail.com"),
) -> ParsedIndeedApplication:
    ...
```

- [ ] **Step 1: Write failing parser tests**

Cover all of these contracts in `app/tests/test_indeed_email_parser.py`:

```python
def test_html_indeed_message_extracts_candidate_job_and_resume_link():
    parsed = parse_indeed_application_email(_realistic_html_message())
    assert parsed.candidate_name == "Wendy Dayanna Marquez Rincon"
    assert parsed.job_title == "Analista de Automatizacion e IA"
    assert parsed.resume_url.startswith("https://")


def test_nested_base64url_multipart_is_decoded():
    parsed = parse_indeed_application_email(_nested_message())
    assert parsed.message_id == "gmail-1"


def test_display_name_cannot_spoof_sender_domain():
    with pytest.raises(NotIndeedMessage):
        parse_indeed_application_email(
            _message(from_value="Indeed <attacker@example.com>")
        )


def test_external_resume_host_is_rejected():
    with pytest.raises(InvalidIndeedResumeLink):
        parse_indeed_application_email(
            _message(resume_url="https://indeed.com.evil.example/cv")
        )


def test_missing_resume_link_is_invalid_but_recognized_indeed_message():
    with pytest.raises(InvalidIndeedMessage):
        parse_indeed_application_email(_message(include_resume_link=False))
```

Use helpers that encode Gmail body `data` as base64url and construct nested `multipart/alternative` / `multipart/mixed` payloads. Include one plain-text fallback test.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q app/tests/test_indeed_email_parser.py
```

Expected: module import fails because `indeed_email_parser.py` does not exist.

- [ ] **Step 3: Implement the smallest safe parser**

Implement recursive MIME traversal, body base64url decoding, HTML anchor parsing, plain-text fallback, and strict host validation. Reuse standard-library parsing instead of adding a server dependency.

Host matching must use a boundary-safe helper:

```python
def _host_allowed(host: str, suffixes: tuple[str, ...]) -> bool:
    normalized = host.strip().casefold().rstrip(".")
    return any(
        normalized == suffix or normalized.endswith("." + suffix)
        for suffix in (item.strip().casefold().lstrip(".") for item in suffixes)
        if suffix
    )
```

Validate `urlsplit(url).scheme == "https"` and a nonempty hostname before returning it.

Candidate/job extraction must be deterministic. Prefer explicit visible text patterns from the Indeed email and fail closed when fields cannot be extracted. Do not use an LLM.

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q app/tests/test_indeed_email_parser.py app/tests/test_email_ingestion_parser.py
```

- [ ] **Step 5: Commit**

```bash
git add app/integrations/email_ingestion/indeed_email_parser.py app/tests/test_indeed_email_parser.py
git commit -m "feat: parse Indeed application emails"
```

---

### Task 2: Extend deterministic job resolution with extracted job title

**Files:**
- Modify: `app/domains/candidate_ingestion/job_resolution.py`
- Modify: `app/tests/test_candidate_ingestion_job_resolution.py`

**Interface change:** `resolve_job()` keeps the same signature. It additionally consumes `metadata["job_title"]` before falling back to subject matching.

Resolution order:
1. Explicit owned `job_id`.
2. Exactly one owned job whose normalized title equals normalized `metadata["job_title"]`.
3. Exactly one owned job whose normalized title is contained in normalized subject.
4. Otherwise `None`.

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_extracted_job_title_exact_match_precedes_subject_fallback():
    ...
    resolved = job_resolution.resolve_job(
        db,
        owner_sub="owner-1",
        explicit_job_id=None,
        metadata={
            "job_title": "Analista de Automatización e IA",
            "subject": "Indeed application",
        },
    )
    assert resolved.id == expected.id


def test_duplicate_exact_job_titles_are_ambiguous():
    ...
    assert resolved is None


def test_extracted_job_title_never_resolves_cross_tenant_job():
    ...
    assert resolved is None
```

- [ ] **Step 2: Verify RED**

```bash
pytest -q app/tests/test_candidate_ingestion_job_resolution.py
```

Expected: the new exact-title test returns `None` because only subject matching exists.

- [ ] **Step 3: Implement exact title matching**

Add a small helper or inline pass over `jobs_repository.list_jobs(db, owner_sub=owner_sub)` using the existing `_normalize()`. Return only when the exact-match list length is exactly 1. If exact title is present but ambiguous, return `None` rather than falling through and guessing via subject.

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q app/tests/test_candidate_ingestion_job_resolution.py
```

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidate_ingestion/job_resolution.py app/tests/test_candidate_ingestion_job_resolution.py
git commit -m "feat: resolve ingestion jobs from extracted title"
```

---

### Task 3: Add durable Indeed email resume tasks and migration 011

**Files:**
- Modify: `app/domains/candidate_ingestion/models.py`
- Modify: `app/domains/candidate_ingestion/__init__.py`
- Create: `app/migrations/versions/011_indeed_email_resume_agent.py`
- Create: `app/tests/test_indeed_email_resume_tasks.py`
- Modify: `app/tests/test_postgres_migrations.py`

**Model:**

```python
class IndeedEmailResumeTask(Base):
    __tablename__ = "indeed_email_resume_tasks"
    __table_args__ = (
        UniqueConstraint(
            "ingestion_event_id",
            name="uq_indeed_email_resume_task_event",
        ),
        Index("idx_indeed_email_resume_task_claim", "status", "available_at", "created_at"),
        Index("idx_indeed_email_resume_task_owner_status", "owner_sub", "status"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    ingestion_event_id = Column(
        UUID(as_uuid=False),
        ForeignKey("candidate_ingestion_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    candidate_name = Column(Text, nullable=False)
    job_title = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="WAITING_DOWNLOAD")
    lease_token = Column(Text, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error_code = Column(Text, nullable=True)
    last_error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
```

`available_at` is the concrete persistence field used to implement the spec's required retry backoff.

- [ ] **Step 1: Write failing model/migration tests**

Tests must prove:
- table is registered in `Base.metadata`;
- unresolved `job_id` is allowed;
- `ingestion_event_id` is one-to-one unique;
- task defaults to `WAITING_DOWNLOAD`, attempt 0, no lease;
- migration file is revision `011`, down revision `010`;
- PostgreSQL smoke expects `indeed_email_resume_tasks` and Alembic head `011`.

- [ ] **Step 2: Verify RED**

```bash
pytest -q app/tests/test_indeed_email_resume_tasks.py app/tests/test_postgres_migrations.py
```

SQLite model test should fail because the model/table does not exist; PostgreSQL smoke may skip locally.

- [ ] **Step 3: Implement ORM model and additive migration**

Create migration `011_indeed_email_resume_agent.py` with explicit columns, FK constraints, unique constraint and the two indexes above. `downgrade()` removes the table.

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q app/tests/test_indeed_email_resume_tasks.py app/tests/test_candidate_ingestion_models.py
```

Run PostgreSQL migration smoke in CI and confirm revision `011`.

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidate_ingestion/models.py app/domains/candidate_ingestion/__init__.py app/migrations/versions/011_indeed_email_resume_agent.py app/tests/test_indeed_email_resume_tasks.py app/tests/test_postgres_migrations.py
git commit -m "feat: persist Indeed email resume tasks"
```

---

### Task 4: Route Indeed emails into durable download tasks during Gmail sync

**Files:**
- Create: `app/domains/candidate_ingestion/indeed_email_service.py`
- Modify: `app/domains/candidate_ingestion/email_service.py`
- Create: `app/tests/test_indeed_email_discovery.py`
- Modify: `app/tests/test_email_ingestion_service.py`
- Modify: `app/tests/test_gmail_mailbox_sync.py`

**Service interface:**

```python
@dataclass(frozen=True)
class IndeedEmailDiscoveryResult:
    event: CandidateIngestionEvent
    task: IndeedEmailResumeTask | None
    created: bool


def discover_indeed_email(
    db: Session,
    *,
    owner_sub: str,
    source_account: str,
    raw_message: dict,
) -> IndeedEmailDiscoveryResult | None:
    """Return None only when the message is not from Indeed."""
```

- [ ] **Step 1: Write failing discovery tests**

Prove:
- recognized Indeed email with no attachment creates one event and one `WAITING_DOWNLOAD` task;
- metadata stores only safe fields (`gmail_message_id`, sender, subject, candidate_name, job_title, timestamps), never `resume_url`;
- a unique job title writes both `event.job_id` and `task.job_id`;
- ambiguous/missing job still creates the download task with nullable job;
- missing/invalid resume link creates/reuses event as `NEEDS_REVIEW` with a specific safe error and no task;
- the same Gmail message sync twice returns the same event/task and never duplicates;
- a non-Indeed sender falls through to existing generic attachment ingestion unchanged.

- [ ] **Step 2: Verify RED**

```bash
pytest -q app/tests/test_indeed_email_discovery.py app/tests/test_email_ingestion_service.py
```

- [ ] **Step 3: Implement discovery and narrow change to `ingest_gmail_message()`**

Immediately after `raw_message = mailbox_client.get_message(message_id)`, call the specialized discovery service only for provider `INDEED`. If it returns a result, return `EmailIngestionResult(event=result.event, created=result.created)` without invoking the generic attachment parser.

For recognized valid Indeed email:

```python
event.status = "RECEIVED"
event.last_error_code = "RESUME_DOWNLOAD_PENDING"
event.last_error_message = "El CV de Indeed esta pendiente de descarga."
```

For a malformed recognized Indeed message, persist `NEEDS_REVIEW` with `INDEED_EMAIL_INVALID` or `INDEED_RESUME_LINK_INVALID`; never put the rejected URL in `last_error_message`.

Use `IntegrityError` recovery so event/task creation remains safe under duplicate sync races.

- [ ] **Step 4: Verify GREEN and Gmail cursor behavior**

```bash
pytest -q \
  app/tests/test_indeed_email_discovery.py \
  app/tests/test_email_ingestion_service.py \
  app/tests/test_gmail_mailbox_sync.py \
  app/tests/test_gmail_history_recovery.py
```

- [ ] **Step 5: Commit**

```bash
git add app/domains/candidate_ingestion/indeed_email_service.py app/domains/candidate_ingestion/email_service.py app/tests/test_indeed_email_discovery.py app/tests/test_email_ingestion_service.py app/tests/test_gmail_mailbox_sync.py
git commit -m "feat: create resume tasks from Indeed emails"
```

---

### Task 5: Implement task claim, lease, heartbeat and retry semantics

**Files:**
- Create: `app/domains/candidate_ingestion/indeed_email_repository.py`
- Create: `app/domains/candidate_ingestion/indeed_email_agent_service.py`
- Create: `app/tests/test_indeed_email_resume_leases.py`

**Primary service interfaces:**

```python
@dataclass(frozen=True)
class ClaimedResumeTask:
    task_id: str
    candidate_name: str
    job_title: str
    lease_token: str
    lease_expires_at: datetime


def claim_next_task(db: Session, *, owner_sub: str, now: datetime | None = None) -> ClaimedResumeTask | None: ...
def heartbeat(db: Session, *, owner_sub: str, task_id: str, lease_token: str, now: datetime | None = None) -> datetime: ...
def mark_needs_human(db: Session, *, owner_sub: str, task_id: str, lease_token: str, code: str) -> None: ...
def record_failure(db: Session, *, owner_sub: str, task_id: str, lease_token: str, code: str) -> str: ...
def stats(db: Session, *, owner_sub: str) -> dict[str, int]: ...
```

- [ ] **Step 1: Write failing lease tests**

Tests must prove:
- first claim returns the oldest eligible task;
- a second concurrent/serial claim cannot return an actively leased task;
- expired `CLAIMED` task is reclaimable with a new lease token;
- stale lease token cannot heartbeat, fail or upload;
- heartbeat extends the same lease by 600 seconds;
- `NEEDS_HUMAN` clears lease and stays out of normal claim until explicitly resumed;
- failure at attempt 1 -> `RETRY`, `available_at = now + 15s`;
- failure at attempt 2 -> `RETRY`, `available_at = now + 60s`;
- failure at attempt 3 -> `FAILED`;
- 82 completed tasks stay terminal after process restart while task 83 is reclaimable.

- [ ] **Step 2: Verify RED**

```bash
pytest -q app/tests/test_indeed_email_resume_leases.py
```

- [ ] **Step 3: Implement repository claim safely**

For PostgreSQL, select the candidate row in a transaction using `with_for_update(skip_locked=True)` ordered by `created_at`, then mutate it and commit. For SQLite tests, use the same eligibility predicate without `skip_locked`; tests remain single-process.

Eligibility:

```text
WAITING_DOWNLOAD
RETRY where available_at is null or <= now
CLAIMED where lease_expires_at < now
```

Generate lease tokens with `secrets.token_urlsafe(32)`. Never log them.

- [ ] **Step 4: Implement service state transitions**

Use `hmac.compare_digest()` when comparing supplied lease token to stored token. Clear lease fields whenever a task leaves `CLAIMED`.

`NEEDS_HUMAN` is resumed through a dedicated service method `resume_after_human(...)` that sets `WAITING_DOWNLOAD`, clears human error and does not increment attempt count until the next claim.

- [ ] **Step 5: Verify GREEN**

```bash
pytest -q app/tests/test_indeed_email_resume_leases.py app/tests/test_candidate_ingestion_queue.py
```

- [ ] **Step 6: Commit**

```bash
git add app/domains/candidate_ingestion/indeed_email_repository.py app/domains/candidate_ingestion/indeed_email_agent_service.py app/tests/test_indeed_email_resume_leases.py
git commit -m "feat: add leased Indeed resume queue"
```

---

### Task 6: Add least-privilege machine authentication and configuration

**Files:**
- Modify: `app/config.py`
- Create: `app/infrastructure/indeed_resume_agent_secret.py`
- Create: `app/domains/candidate_ingestion/indeed_agent_auth.py`
- Modify: `app/tests/test_config.py`
- Create: `app/tests/test_indeed_agent_auth.py`

**Settings:**

```python
@dataclass(frozen=True)
class IndeedResumeAgentSettings:
    secret_id: str
    lease_seconds: int
    max_attempts: int
    sender_domains: tuple[str, ...]
    resume_host_suffixes: tuple[str, ...]
```

Defaults:

```text
secret_id=/ai-recruiter/prod/indeed-resume-agent
lease_seconds=600
max_attempts=3
sender_domains=indeedemail.com
resume_host_suffixes=indeed.com,indeedemail.com
```

Secrets Manager JSON contract:

```json
{
  "enabled": true,
  "owner_sub": "<Cognito owner sub>",
  "token_sha256": "<64 lowercase hex characters>"
}
```

The plan never commits or logs the actual token.

- [ ] **Step 1: Write failing config/auth tests**

Tests cover defaults, environment overrides, missing header -> 401, disabled secret -> 503, invalid token -> 401, valid token -> an `AgentPrincipal(owner_sub=...)`, and response/error serialization never includes `token_sha256`.

Use header:

```text
X-ASIATI-Agent-Token: <raw machine token>
```

- [ ] **Step 2: Verify RED**

```bash
pytest -q app/tests/test_config.py app/tests/test_indeed_agent_auth.py
```

- [ ] **Step 3: Implement secret reader and FastAPI dependency**

Follow the existing `GmailOAuthSecretStore` boto3 Session/profile pattern. Hash the supplied raw token with SHA-256 and compare the hex digest with `hmac.compare_digest()`.

```python
@dataclass(frozen=True)
class AgentPrincipal:
    owner_sub: str


def get_indeed_resume_agent_principal(
    token: str | None = Header(default=None, alias="X-ASIATI-Agent-Token"),
) -> AgentPrincipal:
    ...
```

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q app/tests/test_indeed_agent_auth.py app/tests/test_gmail_oauth_store.py app/tests/test_config.py
```

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/infrastructure/indeed_resume_agent_secret.py app/domains/candidate_ingestion/indeed_agent_auth.py app/tests/test_config.py app/tests/test_indeed_agent_auth.py
git commit -m "feat: authenticate Indeed resume agent"
```

---

### Task 7: Expose agent endpoints, resolve resume URL on claim, and ingest uploaded PDF

**Files:**
- Create: `app/domains/candidate_ingestion/indeed_agent_router.py`
- Modify: `app/domains/candidate_ingestion/indeed_email_agent_service.py`
- Modify: `app/bootstrap.py`
- Create: `app/tests/test_indeed_agent_routes.py`
- Create: `app/tests/test_indeed_agent_upload.py`

**HTTP contract:**

```text
POST /api/agents/indeed-resume/claim
POST /api/agents/indeed-resume/{task_id}/heartbeat
POST /api/agents/indeed-resume/{task_id}/resume
POST /api/agents/indeed-resume/{task_id}/needs-human
POST /api/agents/indeed-resume/{task_id}/fail
POST /api/agents/indeed-resume/{task_id}/resume-after-human
GET  /api/agents/indeed-resume/stats
```

All endpoints require `X-ASIATI-Agent-Token`. Task mutation endpoints additionally require:

```text
X-ASIATI-Lease-Token: <lease token returned by claim>
```

`resume-after-human` does not use the expired old lease; it requires only machine auth and owner scope, because the task is already in `NEEDS_HUMAN`.

- [ ] **Step 1: Write failing route/auth tests**

Test response codes and owner isolation. A machine credential for owner A cannot claim or mutate owner B tasks. Empty queue returns `204 No Content` from claim.

- [ ] **Step 2: Write failing claim URL-resolution tests**

Claim must:
1. lease the task;
2. load the linked event's `raw_metadata["gmail_message_id"]`;
3. build a Gmail client from the already-resolved Gmail OAuth settings;
4. call `get_message(message_id)`;
5. re-run `parse_indeed_application_email()`;
6. return the current `resume_url` only in the claim response.

If Gmail or the parsed link is unavailable after claim, release/transition safely to `RETRY` or `NEEDS_REVIEW`; do not leave a dead lease. Assert the URL does not appear in DB metadata or error messages.

Example success response:

```json
{
  "task_id": "uuid",
  "candidate_name": "Wendy Dayanna Marquez Rincon",
  "job_title": "Analista de Automatizacion e IA",
  "resume_url": "https://secure.indeed.com/...",
  "lease_token": "opaque",
  "lease_expires_at": "2026-09-17T18:10:00+00:00"
}
```

- [ ] **Step 3: Write failing upload tests**

Cover:
- valid PDF creates exactly one CandidateIngestionDocument;
- fake `.pdf` without `%PDF-` -> 422;
- content type other than `application/pdf` -> 422;
- payload above 15 MiB -> 413;
- stale/incorrect lease -> 409;
- same upload repeated after a client timeout is idempotent when SHA-256 matches;
- an existing different document for the same event -> 409 rather than silently replacing it;
- successful upload sets event `STORED`, clears `RESUME_DOWNLOAD_PENDING`, sets task `COMPLETED`, and leaves `queue_dispatched_at=None` so the existing repair cycle will dispatch it.

- [ ] **Step 4: Verify RED**

```bash
pytest -q app/tests/test_indeed_agent_routes.py app/tests/test_indeed_agent_upload.py
```

- [ ] **Step 5: Implement API and bounded upload reader**

Use `UploadFile` and read at most `MAX_DOCUMENT_BYTES + 1` bytes before rejecting oversized input. Validate magic bytes server-side.

Storage handoff:

```python
source_key = EmailIngestionStorage().store_source_document(
    event_id=event.id,
    attachment_id=f"indeed-agent-{task.id}",
    filename=safe_filename,
    data=data,
    content_type="application/pdf",
)
repository.create_document(
    db,
    ingestion_event_id=event.id,
    filename=safe_filename,
    content_type="application/pdf",
    size_bytes=len(data),
    source_s3_key=source_key,
    document_sha256=hashlib.sha256(data).hexdigest(),
    status="STORED",
)
```

Do not directly call Bedrock/evaluation/ranking from the agent route.

- [ ] **Step 6: Register router and verify worker handoff**

Add the router in `app/bootstrap.py`. Add an integration test that uploads a PDF, calls `candidate_ingestions.dispatch_undispatched_ingestions(db)` with SQS mocked, and verifies the existing event id is queued once.

- [ ] **Step 7: Verify GREEN**

```bash
pytest -q \
  app/tests/test_indeed_agent_routes.py \
  app/tests/test_indeed_agent_upload.py \
  app/tests/test_candidate_ingestion_dispatcher.py \
  app/tests/test_candidate_ingestion_worker.py \
  app/tests/test_gmail_ingestion_routes.py
```

- [ ] **Step 8: Commit**

```bash
git add app/domains/candidate_ingestion/indeed_agent_router.py app/domains/candidate_ingestion/indeed_email_agent_service.py app/bootstrap.py app/tests/test_indeed_agent_routes.py app/tests/test_indeed_agent_upload.py
git commit -m "feat: expose Indeed resume agent API"
```

---

### Task 8: Configure Gmail for Indeed-link discovery and document production operations

**Files:**
- Modify: `docs/gmail-candidate-ingestion-setup.md`
- Create: `docs/indeed-resume-agent-operations.md`
- Modify: `app/tests/test_gmail_runtime_secret.py`
- Modify: `app/tests/test_gmail_safe_configuration.py`

**Target production Gmail runtime configuration after backend + agent credential are deployed:**

```json
{
  "enabled": true,
  "query": "from:indeedemail.com",
  "allowed_senders": [],
  "ingestion_provider": "INDEED"
}
```

The `from:` query is a mailbox-discovery restriction only. The specialized parser still validates the actual parsed sender domain. Do not add `has:attachment` because Indeed CV emails are link-based.

- [ ] **Step 1: Write failing configuration-contract tests**

Update tests so `from:indeedemail.com` is accepted as a safe filter and a runtime secret with that query remains `safe_filter=True`. Keep the test proving a broad unqualified query is rejected.

- [ ] **Step 2: Verify RED if implementation/docs contract is incomplete**

```bash
pytest -q app/tests/test_gmail_safe_configuration.py app/tests/test_gmail_runtime_secret.py
```

- [ ] **Step 3: Update operator docs**

Document this exact cutover order:
1. deploy migration/backend;
2. create `/ai-recruiter/prod/indeed-resume-agent` with `enabled`, `owner_sub`, and `token_sha256`;
3. provision raw token into Windows Credential Manager on Katherine's PC;
4. install/start agent and verify machine auth/stats;
5. update `/ai-recruiter/prod/gmail-oauth` to `enabled=true`, `query=from:indeedemail.com`;
6. run one Gmail sync;
7. smoke test one real application;
8. batch 5-10;
9. only then process the larger backlog.

Document rollback: set Gmail `enabled=false`; leave durable tasks untouched; stop local agent. No candidate data needs deletion.

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q app/tests/test_gmail_safe_configuration.py app/tests/test_gmail_runtime_secret.py
```

- [ ] **Step 5: Commit**

```bash
git add docs/gmail-candidate-ingestion-setup.md docs/indeed-resume-agent-operations.md app/tests/test_gmail_runtime_secret.py app/tests/test_gmail_safe_configuration.py
git commit -m "docs: add Indeed resume bridge operations"
```

---

### Task 9: Full backend verification before production mutation

No production secret or Gmail runtime change is performed until all checks below pass.

- [ ] **Step 1: Run focused feature suite**

```bash
pytest -q \
  app/tests/test_indeed_email_parser.py \
  app/tests/test_indeed_email_discovery.py \
  app/tests/test_indeed_email_resume_tasks.py \
  app/tests/test_indeed_email_resume_leases.py \
  app/tests/test_indeed_agent_auth.py \
  app/tests/test_indeed_agent_routes.py \
  app/tests/test_indeed_agent_upload.py
```

Expected: all green.

- [ ] **Step 2: Run regression suites around shared paths**

```bash
pytest -q \
  app/tests/test_email_ingestion_parser.py \
  app/tests/test_email_ingestion_service.py \
  app/tests/test_gmail_mailbox_sync.py \
  app/tests/test_gmail_history_recovery.py \
  app/tests/test_gmail_incremental_transport.py \
  app/tests/test_candidate_ingestion_job_resolution.py \
  app/tests/test_candidate_ingestion_worker.py \
  app/tests/test_candidate_ingestion_dispatcher.py \
  app/tests/test_indeed_resume_download.py \
  app/tests/test_indeed_resume_ingestion.py \
  app/tests/test_indeed_resume_queue.py \
  app/tests/test_indeed_resume_routes.py \
  app/tests/test_indeed_resume_worker.py
```

Expected: all green.

- [ ] **Step 3: Run complete backend suite**

```bash
pytest -q app/tests
```

Expected: all green; PostgreSQL-only migration smoke may skip outside the CI PostgreSQL job.

- [ ] **Step 4: Verify migration on PostgreSQL CI**

Confirm `test_alembic_head_builds_current_postgres_schema` passes and reports revision `011` with `indeed_email_resume_tasks` present.

- [ ] **Step 5: Secret scan and diff review**

```bash
git diff --check
git grep -nE "(client_secret|refresh_token|X-ASIATI-Agent-Token|token_sha256)" -- ':!docs/superpowers/plans/*' ':!app/tests/*'
```

Review every result. Configuration keys are allowed; real credential values are not.

- [ ] **Step 6: Commit any verification-only fixes, then stop before AWS cutover**

Implementation is complete only when tests prove the backend contract. Production AWS secret creation/update is an operational cutover step performed after the Windows-agent plan is also green.