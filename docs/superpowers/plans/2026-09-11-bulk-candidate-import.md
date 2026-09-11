# Bulk Candidate Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a durable, tenant-safe bulk CV importer for up to 500 PDF/DOCX documents (directly or inside ZIPs) that uploads to S3, deduplicates candidates, ingests one Bedrock Knowledge Base batch, evaluates candidates automatically, materializes ranking, and drives an animated progress UI from persisted backend state.

**Architecture:** The browser uploads files directly to a private staging S3 bucket using presigned POSTs. FastAPI persists `ImportBatch`/`ImportItem` state and dispatches only a batch ID through SQS Standard; a separate worker container resumes an idempotent state machine from PostgreSQL, uses the existing Candidates/Evaluations/Ranking boundaries, and records progress polled by React. The existing synchronous `/api/candidates/bulk` contract stays unchanged.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, boto3, Amazon S3, Amazon SQS + DLQ, Amazon Bedrock Knowledge Bases, PyMuPDF, python-docx, React/Vite, Axios, Vitest, CSS animations.

**Spec:** `docs/superpowers/specs/2026-09-11-bulk-candidate-import-design.md`

## Global Constraints

- Maximum **500 candidate documents per import batch**.
- Accepted inputs: **PDF, DOCX, ZIP**; nested archives are rejected.
- Candidate document limit: **15 MiB**; compressed ZIP limit: **500 MiB**; total expanded document bytes: **1 GiB**.
- Deduplication is owner-scoped and automatic only by `DOCUMENT_SHA256`, normalized `EMAIL`, or normalized `PHONE`; name alone never merges.
- No CV/source-origin field and no Browser Use/Computrabajo automation.
- Direct browser-to-S3 presigned POST upload; CV bytes do not traverse FastAPI.
- SQS Standard + DLQ, at-least-once delivery, one worker process in V1.
- One logical Bedrock ingestion per changed batch using a deterministic `clientToken`.
- Automatic evaluation and final ranking; ranking materialization must not invoke a second evaluation pass.
- PostgreSQL is the source of truth for progress/recovery.
- REST polling drives UI progress; no SSE/WebSocket in V1.
- No fake cross-stage percentage; Bedrock ingestion and ranking are indeterminate stages.
- Preserve existing Candidate, Evaluation, Job, Ranking, auth, ASIATI branding, and legacy bulk-upload contracts.
- Strict RED -> GREEN TDD; no production implementation is added before its failing test is observed.

---

## File Structure Map

### Backend persistence/domain

- Create `app/migrations/versions/003_candidate_imports.py` — schema for import batches/items/identities.
- Modify `app/models.py` — ORM mirrors migration 003.
- Create `app/domains/candidate_imports/{__init__,exceptions,presenter,repository,router,schemas,service,rules}.py` — application boundary.
- Modify `app/domains/candidates/repository.py` — targeted helpers for importer-safe candidate identity/update operations.
- Modify `app/domains/ranking/service.py` — ranking materialization from persisted evaluations only.
- Modify `app/bootstrap.py` — include candidate-import router.
- Modify `app/config.py` — import-specific environment getters.

### Infrastructure/worker

- Create `app/infrastructure/imports/storage.py` — presigned staging operations and canonical CV writes.
- Create `app/infrastructure/imports/queue.py` — SQS transport.
- Create `app/infrastructure/imports/documents.py` — PDF/DOCX parsing, contact extraction, ZIP safety.
- Create `app/infrastructure/imports/ingestion.py` — idempotent Bedrock ingestion start/status.
- Create `app/workers/candidate_imports.py` — queue loop/state-machine execution.
- Create `app/scripts/backfill_candidate_identities.py` — idempotent legacy identity bootstrap.

### AWS/deployment

- Create `infra/candidate-import.yml` — S3 staging bucket, SQS queue/DLQ, resource policies/outputs.
- Create `scripts/deploy-worker.sh` — worker container deployment with Roles Anywhere mounts.
- Modify `.github/workflows/deploy.yml` — provision/configure runtime and deploy/verify worker.
- Modify `.env.example` — import environment variables.

### Frontend

- Create `frontend-react/src/features/candidate-import/api.js` — import API and direct-S3 upload helpers.
- Create `frontend-react/src/features/candidate-import/useCandidateImport.js` — upload/polling state machine.
- Create `frontend-react/src/features/candidate-import/CandidateImportModal.jsx` — selection/upload surface.
- Create `frontend-react/src/features/candidate-import/ImportProgress.jsx` — real-stage progress.
- Create `frontend-react/src/features/candidate-import/ImportSummary.jsx` — terminal summary/action.
- Create `frontend-react/src/features/candidate-import/candidate-import.css` — ASIATI motion and reduced-motion rules.
- Modify `frontend-react/src/pages/Candidates.jsx` — replace legacy upload UI integration only; preserve candidate management.

### Tests

- Create `app/tests/test_candidate_import_models.py`.
- Create `app/tests/test_candidate_import_rules.py`.
- Create `app/tests/test_candidate_import_documents.py`.
- Create `app/tests/test_candidate_import_infrastructure.py`.
- Create `app/tests/test_candidate_import_domain.py`.
- Create `app/tests/test_candidate_import_api.py`.
- Create `app/tests/test_candidate_import_worker.py`.
- Create `app/tests/test_candidate_identity_backfill.py`.
- Modify `app/tests/test_architecture_boundaries.py`.
- Modify `app/tests/test_deploy_contract.py`.
- Create `frontend-react/src/__tests__/candidate-import.test.jsx`.

---

### Task 1: Persist import batches, items, and strong candidate identities

**Files:**
- Create: `app/migrations/versions/003_candidate_imports.py`
- Modify: `app/models.py`
- Create: `app/tests/test_candidate_import_models.py`

**Interfaces:**
- Produces ORM classes `ImportBatch`, `ImportItem`, `CandidateIdentity` in `app.models`.
- Produces DB uniqueness `UNIQUE(owner_sub, kind, value)` on candidate identities.
- Produces cascade semantics required by later repository/service tasks.

- [ ] **Step 1: Write failing schema/model tests**

```python
# app/tests/test_candidate_import_models.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem, Job


def test_import_models_create_expected_tables_and_identity_uniqueness():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"import_batches", "import_items", "candidate_identities"} <= names


def test_candidate_identity_is_unique_per_owner_kind_value():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        candidate = Candidate(name="Ana", owner_sub="owner-a")
        db.add(candidate)
        db.commit()
        db.add(CandidateIdentity(owner_sub="owner-a", candidate_id=candidate.id, kind="EMAIL", value="ana@example.com"))
        db.commit()
        db.add(CandidateIdentity(owner_sub="owner-a", candidate_id=candidate.id, kind="EMAIL", value="ana@example.com"))
        try:
            db.commit()
        except Exception:
            db.rollback()
        else:
            raise AssertionError("duplicate identity must violate unique constraint")
```

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_models.py -q`

Expected: collection/import failure because `ImportBatch`, `ImportItem`, and `CandidateIdentity` do not exist.

- [ ] **Step 3: Add ORM models and migration 003**

Add model fields exactly matching the spec. Core declarations include:

```python
class ImportBatch(Base):
    __tablename__ = "import_batches"
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    owner_sub = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="UPLOADING")
    current_stage = Column(Text, nullable=False, default="UPLOADING")
    upload_total = Column(Integer, nullable=False, default=0)
    uploaded_items = Column(Integer, nullable=False, default=0)
    total_items = Column(Integer, nullable=False, default=0)
    processed_items = Column(Integer, nullable=False, default=0)
    successful_items = Column(Integer, nullable=False, default=0)
    reused_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    evaluated_items = Column(Integer, nullable=False, default=0)
    evaluation_failed_items = Column(Integer, nullable=False, default=0)
    ranking_ready = Column(Boolean, nullable=False, default=False)
    ranking_version = Column(Integer, nullable=True)
    bedrock_ingestion_job_id = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    queue_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    processing_token = Column(Text, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(Text, nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CandidateIdentity(Base):
    __tablename__ = "candidate_identities"
    __table_args__ = (UniqueConstraint("owner_sub", "kind", "value", name="uq_candidate_identity_owner_kind_value"),)
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_sub = Column(Text, nullable=False)
    candidate_id = Column(UUID(as_uuid=False), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    kind = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
```

`ImportItem.candidate_id` uses `ON DELETE SET NULL`; `ImportBatch.job_id` uses `ON DELETE CASCADE`; migration creates indexes on `(owner_sub, created_at)`, `(job_id, created_at)`, `(status, heartbeat_at)`, and `(batch_id, status)`.

- [ ] **Step 4: Run model tests and migration upgrade/downgrade smoke**

Run:

```bash
python -m pytest app/tests/test_candidate_import_models.py -q
DATABASE_URL=sqlite:////tmp/import-migration.db alembic -c app/alembic.ini upgrade head
DATABASE_URL=sqlite:////tmp/import-migration.db alembic -c app/alembic.ini downgrade 002
```

Expected: model tests PASS; Alembic reaches `003`, then returns to `002` without error.

- [ ] **Step 5: Commit persistence slice**

```bash
git add app/models.py app/migrations/versions/003_candidate_imports.py app/tests/test_candidate_import_models.py
git commit -m "feat: add candidate import persistence model"
```

---

### Task 2: Implement deterministic import rules and safe document/archive parsing

**Files:**
- Create: `app/domains/candidate_imports/__init__.py`
- Create: `app/domains/candidate_imports/rules.py`
- Create: `app/infrastructure/imports/__init__.py`
- Create: `app/infrastructure/imports/documents.py`
- Create: `app/tests/test_candidate_import_rules.py`
- Create: `app/tests/test_candidate_import_documents.py`

**Interfaces:**
- Produces `normalize_email(value: str) -> str`, `normalize_phone(value: str) -> str`, `document_sha256(data: bytes) -> str`.
- Produces `extract_document(data: bytes, filename: str) -> ParsedDocument`.
- Produces `expand_zip(data: bytes) -> list[ExpandedDocument]` with archive safety enforcement.
- Produces `resolve_identity_candidates(matches: dict[str, str]) -> str | None` that raises `IdentityConflict` when strong identities point to different candidate IDs.

- [ ] **Step 1: Write failing rule tests**

```python
from app.domains.candidate_imports.rules import IdentityConflict, normalize_email, normalize_phone, resolve_identity_candidates


def test_identity_normalization_and_conflict_policy():
    assert normalize_email("  ANA@Example.COM ") == "ana@example.com"
    assert normalize_phone("+57 (300) 123-4567") == "+573001234567"
    assert resolve_identity_candidates({"EMAIL": "c1", "PHONE": "c1"}) == "c1"
    assert resolve_identity_candidates({}) is None
    try:
        resolve_identity_candidates({"EMAIL": "c1", "PHONE": "c2"})
    except IdentityConflict:
        pass
    else:
        raise AssertionError("conflicting strong identities must not merge")
```

- [ ] **Step 2: Run rules test and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_rules.py -q`

Expected: import failure because candidate-import rules do not exist.

- [ ] **Step 3: Implement minimal rules**

```python
class IdentityConflict(Exception):
    pass


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def normalize_phone(value: str) -> str:
    raw = value.strip()
    prefix = "+" if raw.startswith("+") else ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"{prefix}{digits}"


def resolve_identity_candidates(matches: dict[str, str]) -> str | None:
    ids = {candidate_id for candidate_id in matches.values() if candidate_id}
    if len(ids) > 1:
        raise IdentityConflict("IDENTITY_CONFLICT")
    return next(iter(ids), None)
```

- [ ] **Step 4: Add failing PDF/DOCX/ZIP tests**

Create in-memory fixtures in `test_candidate_import_documents.py` using PyMuPDF, python-docx, and `zipfile`; assert:

```python
def test_expand_zip_rejects_traversal_and_nested_archives():
    traversal = make_zip({"../evil.pdf": minimal_pdf_bytes("Ana ana@example.com")})
    nested = make_zip({"nested.zip": make_zip({"cv.pdf": minimal_pdf_bytes("Ana")})})
    with pytest.raises(UnsafeArchive):
        expand_zip(traversal)
    with pytest.raises(UnsafeArchive):
        expand_zip(nested)
```

Also assert PDF/DOCX extraction returns header text, unambiguous email/phone, and filename-stem fallback name.

- [ ] **Step 5: Run document tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_documents.py -q`

Expected: import failure because `documents.py` is missing.

- [ ] **Step 6: Implement parsing with hard limits**

Use `fitz.open(stream=data, filetype="pdf")`, `docx.Document(io.BytesIO(data))`, and `zipfile.ZipFile(io.BytesIO(data))`. Before extracting ZIP members enforce:

```python
if info.is_dir():
    continue
path = PurePosixPath(info.filename)
if path.is_absolute() or ".." in path.parts:
    raise UnsafeArchive("UNSAFE_ARCHIVE_PATH")
if info.external_attr >> 16 & 0o170000 == 0o120000:
    raise UnsafeArchive("ARCHIVE_SYMLINK")
if path.suffix.lower() not in {".pdf", ".docx"}:
    if path.suffix.lower() in {".zip", ".tar", ".gz", ".rar", ".7z"}:
        raise UnsafeArchive("NESTED_ARCHIVE")
    continue
```

Limit direct docs to `15 * 1024 * 1024`, ZIP compressed bytes to `500 * 1024 * 1024`, expanded aggregate to `1024 * 1024 * 1024`, and discovered docs to 500.

- [ ] **Step 7: Run rule/document tests**

Run: `python -m pytest app/tests/test_candidate_import_rules.py app/tests/test_candidate_import_documents.py -q`

Expected: PASS.

- [ ] **Step 8: Commit deterministic parsing slice**

```bash
git add app/domains/candidate_imports app/infrastructure/imports app/tests/test_candidate_import_rules.py app/tests/test_candidate_import_documents.py
git commit -m "feat: add safe candidate import parsing rules"
```

---

### Task 3: Add import configuration and AWS infrastructure adapters

**Files:**
- Modify: `app/config.py`
- Create: `app/infrastructure/imports/storage.py`
- Create: `app/infrastructure/imports/queue.py`
- Create: `app/infrastructure/imports/ingestion.py`
- Create: `app/tests/test_candidate_import_infrastructure.py`
- Modify: `app/tests/test_config.py`
- Modify: `.env.example`

**Interfaces:**
- `create_staging_presigned_post(batch_id, item_id, content_type, size_bytes) -> dict`.
- `head_staging_object(key) -> dict`, `read_staging_object(key) -> bytes`, `delete_staging_prefix(batch_id) -> None`.
- `write_canonical_candidate_document(candidate_id, candidate_name, filename, data) -> bool` returns whether canonical content changed.
- `send_import_batch(batch_id) -> None`, `receive_import_messages() -> list[dict]`, `delete_message(receipt_handle)`, `extend_visibility(receipt_handle, seconds)`.
- `start_batch_ingestion(batch_id) -> tuple[str, str]`, `get_ingestion_status(job_id) -> str`.

- [ ] **Step 1: Write failing adapter contract tests with fake boto clients**

```python
def test_sqs_message_contains_only_schema_and_batch_id(fake_sqs, monkeypatch):
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake_sqs)
    queue.send_import_batch("batch-1")
    body = json.loads(fake_sqs.sent[0]["MessageBody"])
    assert body == {"schema_version": 1, "batch_id": "batch-1"}


def test_bedrock_start_uses_deterministic_client_token(fake_bedrock, monkeypatch):
    monkeypatch.setattr(ingestion, "_client", lambda: fake_bedrock)
    ingestion.start_batch_ingestion("batch-123")
    assert fake_bedrock.last_request["clientToken"] == ingestion.client_token_for_batch("batch-123")
```

- [ ] **Step 2: Run adapter tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py -q`

Expected: failures for missing adapters/config getters.

- [ ] **Step 3: Add exact config getters**

```python
def get_import_staging_bucket() -> str:
    return os.environ["IMPORT_STAGING_BUCKET"]


def get_import_queue_url() -> str:
    return os.environ["IMPORT_QUEUE_URL"]


def get_import_evaluation_concurrency() -> int:
    return int(os.getenv("IMPORT_EVALUATION_CONCURRENCY", "3"))


def get_import_lease_timeout_seconds() -> int:
    return int(os.getenv("IMPORT_LEASE_TIMEOUT_SECONDS", "300"))
```

Add `.env.example` keys with non-secret placeholders such as `IMPORT_STAGING_BUCKET=ai-recruiter-import-staging-ACCOUNT`, `IMPORT_QUEUE_URL=https://sqs.us-east-2.amazonaws.com/ACCOUNT/ai-recruiter-imports`, and concurrency/lease defaults.

- [ ] **Step 4: Implement adapters with injected/private client factories**

Presigned POST must bind exact object key and content length:

```python
return s3.generate_presigned_post(
    Bucket=bucket,
    Key=key,
    Fields={"Content-Type": content_type},
    Conditions=[
        {"Content-Type": content_type},
        ["content-length-range", 1, size_bytes],
    ],
    ExpiresIn=3600,
)
```

Bedrock token:

```python
def client_token_for_batch(batch_id: str) -> str:
    return hashlib.sha256(f"candidate-import:{batch_id}".encode()).hexdigest()
```

Use existing `_bedrock_session` so Roles Anywhere behavior remains consistent.

- [ ] **Step 5: Run adapter/config tests**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 6: Commit AWS adapter slice**

```bash
git add app/config.py app/infrastructure/imports .env.example app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py
git commit -m "feat: add candidate import aws adapters"
```

---

### Task 4: Build candidate-import repository, identity resolution, and batch creation service

**Files:**
- Create: `app/domains/candidate_imports/exceptions.py`
- Create: `app/domains/candidate_imports/repository.py`
- Create: `app/domains/candidate_imports/schemas.py`
- Create: `app/domains/candidate_imports/presenter.py`
- Create: `app/domains/candidate_imports/service.py`
- Modify: `app/domains/candidates/repository.py`
- Create: `app/tests/test_candidate_import_domain.py`

**Interfaces:**
- `create_batch(db, *, owner_sub, job_id, uploads) -> tuple[ImportBatch, list[dict]]`.
- `complete_batch_uploads(db, *, owner_sub, batch_id) -> ImportBatch`.
- `get_batch(db, *, owner_sub, batch_id) -> ImportBatch`.
- `list_batch_items(db, *, owner_sub, batch_id, page, page_size) -> tuple[list[ImportItem], int]`.
- `list_recent_batches(db, *, owner_sub, job_id, limit) -> list[ImportBatch]`.
- `resolve_or_create_candidate(db, *, owner_sub, parsed_document, sha256, batch_id) -> tuple[Candidate, str]` where outcome is `CREATED` or `REUSED`.

- [ ] **Step 1: Write failing service tests**

```python
def test_create_batch_requires_owned_job_and_returns_presigned_descriptors(db, monkeypatch):
    job = Job(title="Backend", owner_sub="owner-a")
    db.add(job); db.commit()
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", lambda **kwargs: {"url": "https://s3", "fields": {"key": kwargs["key"]}})
    batch, uploads = service.create_batch(
        db,
        owner_sub="owner-a",
        job_id=job.id,
        uploads=[{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    )
    assert batch.status == "UPLOADING"
    assert batch.upload_total == 1
    assert uploads[0]["upload"]["url"] == "https://s3"
```

Add tests for cross-owner job denial, 501st document rejection, identity reuse by email/hash, no name-only reuse, race-safe unique collision, and `IDENTITY_CONFLICT`.

- [ ] **Step 2: Run domain tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_domain.py -q`

Expected: failures for missing service/repository behavior.

- [ ] **Step 3: Implement repository primitives without HTTP/AWS knowledge**

Key signatures:

```python
def get_batch(db: Session, batch_id: str, owner_sub: str) -> ImportBatch | None: ...
def create_batch_record(db: Session, *, job_id: str, owner_sub: str, upload_total: int) -> ImportBatch: ...
def create_upload_item(db: Session, *, batch_id: str, filename: str, key: str, content_type: str, size_bytes: int, kind: str) -> ImportItem: ...
def find_identity(db: Session, *, owner_sub: str, kind: str, value: str) -> CandidateIdentity | None: ...
def attach_identity(db: Session, *, owner_sub: str, candidate_id: str, kind: str, value: str) -> CandidateIdentity: ...
```

Repository commits only at explicit use-case boundaries chosen by service; use `flush()` where identity race handling needs transaction control.

- [ ] **Step 4: Implement candidate repository helpers**

Add owner-scoped helpers:

```python
def update_candidate_document_metadata(db: Session, candidate: Candidate, *, filename: str, email: str | None) -> Candidate:
    metadata = dict(candidate.metadata_ or {})
    metadata["filename"] = filename
    candidate.metadata_ = metadata
    if not candidate.email and email:
        candidate.email = email
    db.flush()
    return candidate
```

Do not overwrite a different non-empty email on reused candidates.

- [ ] **Step 5: Implement service creation/completion and identity resolution**

`complete_batch_uploads()` verifies staging objects, transitions to `QUEUED`, commits `queue_dispatched_at=None`, attempts `queue.send_import_batch(batch.id)`, then persists dispatch time. If queue send fails, leave `QUEUED` + null dispatch timestamp and return/raise a sanitized retryable service error without rolling the batch back to `UPLOADING`.

- [ ] **Step 6: Run domain tests**

Run: `python -m pytest app/tests/test_candidate_import_domain.py app/tests/test_candidates_domain.py -q`

Expected: PASS, including existing candidate tests.

- [ ] **Step 7: Commit application-domain slice**

```bash
git add app/domains/candidate_imports app/domains/candidates/repository.py app/tests/test_candidate_import_domain.py
git commit -m "feat: add candidate import application boundary"
```

---

### Task 5: Expose owner-scoped import HTTP API and architecture guards

**Files:**
- Create: `app/domains/candidate_imports/router.py`
- Modify: `app/bootstrap.py`
- Modify: `app/tests/test_architecture_boundaries.py`
- Create: `app/tests/test_candidate_import_api.py`

**Interfaces:**
- `POST /api/import-batches`.
- `POST /api/import-batches/{batch_id}/complete`.
- `GET /api/import-batches/{batch_id}`.
- `GET /api/import-batches/{batch_id}/items?page=&page_size=`.
- `GET /api/import-batches?job_id=&limit=`.

- [ ] **Step 1: Write failing API tests**

Using FastAPI dependency overrides, assert:

```python
def test_other_owner_cannot_read_batch(client, batch_for_owner_a, auth_as_owner_b):
    response = client.get(f"/api/import-batches/{batch_for_owner_a.id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Importacion no encontrada."}
```

Also test `202` creation, idempotent completion, pagination, sanitized errors, and recent job imports.

- [ ] **Step 2: Run API tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_api.py -q`

Expected: 404 because router is not registered.

- [ ] **Step 3: Implement HTTP-only router**

Pattern:

```python
router = APIRouter(prefix="/api/import-batches", tags=["candidate-imports"])

@router.post("", status_code=202)
def create_import_batch(body: CreateImportBatchRequest, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        batch, uploads = service.create_batch(db, owner_sub=user["sub"], job_id=body.job_id, uploads=[item.model_dump() for item in body.uploads])
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return presenter.batch_created_payload(batch, uploads)
```

Router imports only deps, schemas, service, presenter, exceptions.

- [ ] **Step 4: Add architecture guard**

```python
def test_candidate_import_router_uses_application_boundary_only():
    imports = _imports(APP_ROOT / "domains" / "candidate_imports" / "router.py")
    assert "app.crud" not in imports
    assert not any(".repository" in name and name.startswith("app.domains.") for name in imports)
    assert not any(name.startswith("app.infrastructure") for name in imports)
    assert "app.models" not in imports
```

- [ ] **Step 5: Register router and run tests**

Run: `python -m pytest app/tests/test_candidate_import_api.py app/tests/test_architecture_boundaries.py app/tests/test_bootstrap.py -q`

Expected: PASS.

- [ ] **Step 6: Commit HTTP slice**

```bash
git add app/domains/candidate_imports/router.py app/bootstrap.py app/tests/test_candidate_import_api.py app/tests/test_architecture_boundaries.py
git commit -m "feat: expose candidate import batch api"
```

---

### Task 6: Add ranking materialization without reevaluation

**Files:**
- Modify: `app/domains/ranking/service.py`
- Create/Modify: `app/tests/test_ranking_domain.py` or the repository's existing ranking service test file

**Interfaces:**
- Produces `materialize_ranking_from_evaluations(db, *, job_id: str, owner_sub: str, scope: str = "assigned") -> dict[str, Any]`.
- Must never call `evaluate_candidate_for_job`.

- [ ] **Step 1: Write failing no-reevaluation test**

```python
def test_materialize_ranking_uses_persisted_evaluations_only(db, monkeypatch, job_with_assigned_evaluations):
    monkeypatch.setattr(ranking_service, "evaluate_candidate_for_job", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not evaluate")))
    result = ranking_service.materialize_ranking_from_evaluations(
        db,
        job_id=job_with_assigned_evaluations.id,
        owner_sub="owner-a",
        scope="assigned",
    )
    assert result["ranking_version"] == 1
    assert result["total_candidates"] == 2
```

- [ ] **Step 2: Run ranking test and observe RED**

Run: `python -m pytest app/tests/test_ranking_domain.py -q`

Expected: missing function.

- [ ] **Step 3: Extract shared ranking ordering/persistence helper**

Refactor only enough to reuse existing semantics. New function retrieves assigned candidates and persisted evaluations, maps status/score, sorts with existing `status_order`, assigns positions, and calls existing ranking repository methods under existing job lock.

- [ ] **Step 4: Run ranking regression tests**

Run: `python -m pytest app/tests/test_ranking_domain.py app/tests/test_ranking_*.py -q`

Expected: new and existing ranking behavior PASS.

- [ ] **Step 5: Commit ranking slice**

```bash
git add app/domains/ranking/service.py app/tests/test_ranking_domain.py
git commit -m "feat: materialize ranking from persisted evaluations"
```

---

### Task 7: Implement resumable worker state machine and one-batch Bedrock ingestion

**Files:**
- Create: `app/workers/__init__.py`
- Create: `app/workers/candidate_imports.py`
- Modify: `app/domains/candidate_imports/repository.py`
- Modify: `app/domains/candidate_imports/service.py`
- Create: `app/tests/test_candidate_import_worker.py`

**Interfaces:**
- `process_batch(batch_id: str) -> None` opens/owns DB sessions internally.
- `run_worker_forever() -> None` dispatches undispatched queued batches then long-polls SQS.
- `claim_batch(db, batch_id, token, now, lease_seconds) -> bool`.
- `heartbeat_batch(db, batch_id, token, now) -> None`.
- Worker stages: `VALIDATING -> DEDUPLICATING -> INGESTING -> EVALUATING -> RANKING -> COMPLETED`.

- [ ] **Step 1: Write failing lease/recovery tests**

```python
def test_duplicate_delivery_cannot_claim_fresh_lease(db):
    assert repository.claim_batch(db, batch.id, "worker-a", now, 300) is True
    assert repository.claim_batch(db, batch.id, "worker-b", now + timedelta(seconds=30), 300) is False
    assert repository.claim_batch(db, batch.id, "worker-b", now + timedelta(seconds=301), 300) is True
```

Add tests for resume after processed item, queue-dispatch repair, visibility extension, fifth receive failure, and terminal-message acknowledgement.

- [ ] **Step 2: Run worker tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_worker.py -q`

Expected: missing worker/claim methods.

- [ ] **Step 3: Implement atomic PostgreSQL claim**

Use an `UPDATE ... WHERE` predicate against terminal/fresh lease conditions, set `processing_token`, `heartbeat_at`, increment `attempt_count`, and confirm `rowcount == 1`. Do not use process-local locks.

- [ ] **Step 4: Implement preparation stage**

For each unprocessed top-level item:

```python
raw = storage.read_staging_object(item.staging_s3_key)
if item.kind == "ARCHIVE":
    children = documents.expand_zip(raw)
    service.persist_expanded_documents(db, batch=batch, parent=item, children=children)
else:
    parsed = documents.extract_document(raw, item.original_filename)
    service.prepare_document_item(db, batch=batch, item=item, parsed=parsed, raw=raw)
```

Each document checkpoint persists SHA/contact identity resolution, candidate creation/reuse, idempotent job assignment, canonical write only when changed, and counters.

- [ ] **Step 5: Implement one logical Bedrock ingestion**

If any canonical document changed, call `start_batch_ingestion(batch.id)`, persist `bedrock_ingestion_job_id`, and poll `get_ingestion_status()` until `COMPLETE` or terminal failure. On restart, if the persisted job ID exists, poll it instead of starting again. If start response was lost, deterministic `clientToken` makes the repeated start idempotent.

- [ ] **Step 6: Implement bounded evaluation**

Use `ThreadPoolExecutor(max_workers=get_import_evaluation_concurrency())`; each task opens its own `SessionLocal()` and calls `evaluate_candidate_for_owner(...)`. Update `evaluated_items` and `evaluation_failed_items` transactionally after each terminal evaluation result. Retry only explicit throttling/transient provider failures with bounded backoff; deterministic/data failures are recorded once.

- [ ] **Step 7: Implement ranking/terminalization**

Call:

```python
result = ranking_service.materialize_ranking_from_evaluations(
    db,
    job_id=batch.job_id,
    owner_sub=batch.owner_sub,
    scope="assigned",
)
```

Persist `ranking_ready=True`, ranking version, and terminal status `COMPLETED` vs `COMPLETED_WITH_ERRORS` from counters. Fatal inability to produce a usable ranking becomes `FAILED` with sanitized code/message.

- [ ] **Step 8: Run worker/domain/evaluation/ranking tests**

Run:

```bash
python -m pytest app/tests/test_candidate_import_worker.py app/tests/test_candidate_import_domain.py app/tests/test_evaluations_domain.py app/tests/test_ranking_domain.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit worker slice**

```bash
git add app/workers app/domains/candidate_imports app/tests/test_candidate_import_worker.py
git commit -m "feat: add resumable candidate import worker"
```

---

### Task 8: Bootstrap identities for legacy candidates

**Files:**
- Create: `app/scripts/__init__.py`
- Create: `app/scripts/backfill_candidate_identities.py`
- Create: `app/tests/test_candidate_identity_backfill.py`

**Interfaces:**
- `backfill_candidate_identities(db: Session) -> dict[str, int]`.
- CLI entry: `python -m app.scripts.backfill_candidate_identities`.

- [ ] **Step 1: Write failing backfill tests**

```python
def test_backfill_seeds_email_and_document_hash_without_guessing_collisions(db, monkeypatch):
    db.add_all([
        Candidate(name="Ana", email="ANA@example.com", owner_sub="owner-a"),
        Candidate(name="Ana 2", email="ana@example.com", owner_sub="owner-a"),
    ])
    db.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: None)
    result = backfill.backfill_candidate_identities(db)
    assert result["email_conflicts"] == 1
    assert db.query(CandidateIdentity).filter_by(kind="EMAIL", value="ana@example.com").count() == 0
```

- [ ] **Step 2: Run backfill tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_identity_backfill.py -q`

Expected: missing module/function.

- [ ] **Step 3: Implement idempotent owner-by-owner backfill**

Group normalized emails before insert; only seed email when exactly one candidate in that owner claims it. Read existing canonical candidate file when present and seed `DOCUMENT_SHA256`. Catch identity uniqueness races by rereading, never choosing a winner on conflict. Log counts and IDs only.

- [ ] **Step 4: Run backfill tests twice**

Run: `python -m pytest app/tests/test_candidate_identity_backfill.py -q`

Expected: PASS, including an explicit test that calling the function twice produces no duplicates.

- [ ] **Step 5: Commit backfill slice**

```bash
git add app/scripts app/tests/test_candidate_identity_backfill.py
git commit -m "feat: backfill strong candidate identities"
```

---

### Task 9: Provision S3 staging, SQS queue/DLQ, and least-privilege runtime access

**Files:**
- Create: `infra/candidate-import.yml`
- Modify: `app/tests/test_deploy_contract.py`

**Interfaces:**
- CloudFormation outputs `ImportStagingBucket`, `ImportQueueUrl`, `ImportQueueArn`, `ImportDlqUrl`.
- Queue long-poll wait = 20 seconds; redrive `maxReceiveCount=5`.
- Bucket lifecycle expires staging objects after 1 day; Block Public Access enabled; SSE enabled; CORS contains production origin plus explicit local development origins.

- [ ] **Step 1: Write failing infrastructure contract tests**

```python
def test_candidate_import_template_has_dlq_redrive_and_private_staging_bucket():
    template = yaml.safe_load(Path("infra/candidate-import.yml").read_text())
    resources = template["Resources"]
    assert resources["ImportQueue"]["Properties"]["ReceiveMessageWaitTimeSeconds"] == 20
    assert resources["ImportQueue"]["Properties"]["RedrivePolicy"]["maxReceiveCount"] == 5
    public = resources["ImportStagingBucket"]["Properties"]["PublicAccessBlockConfiguration"]
    assert all(public.values())
```

- [ ] **Step 2: Run deploy-contract test and observe RED**

Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: failure because `infra/candidate-import.yml` does not exist.

- [ ] **Step 3: Create versioned CloudFormation template**

Define `AWS::S3::Bucket`, `AWS::SQS::Queue` DLQ, `AWS::SQS::Queue` main queue with `RedrivePolicy`, and outputs. Do not provision application resources dynamically at FastAPI startup.

- [ ] **Step 4: Add least-privilege policy assertions**

Tests assert S3 actions are scoped to the staging/canonical buckets and SQS actions to the import queue ARNs; no `Resource: "*"` for S3/SQS statements.

- [ ] **Step 5: Run deploy contract tests**

Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit infrastructure slice**

```bash
git add infra/candidate-import.yml app/tests/test_deploy_contract.py
git commit -m "infra: provision candidate import queue and staging bucket"
```

---

### Task 10: Deploy and verify the worker container from the same immutable backend image

**Files:**
- Create: `scripts/deploy-worker.sh`
- Modify: `.github/workflows/deploy.yml`
- Modify: `app/tests/test_deploy_contract.py`

**Interfaces:**
- Worker container name: `ai-recruiter-worker`.
- Worker command: `python -m app.workers.candidate_imports`.
- Same backend image SHA, database URL, Roles Anywhere profile/mounts, region, and Docker network as API.

- [ ] **Step 1: Add failing deployment tests**

```python
def test_worker_deploy_uses_same_sha_image_and_roles_anywhere_mounts():
    script = Path("scripts/deploy-worker.sh").read_text()
    assert "ai-recruiter-worker" in script
    assert "python -m app.workers.candidate_imports" in script
    assert "ECR_TAG" in script
    assert "/run/rolesanywhere/client.crt" in script
    assert "--restart unless-stopped" in script
```

Also assert workflow invokes worker script only after backend tests and image push and verifies container status/image SHA.

- [ ] **Step 2: Run deploy tests and observe RED**

Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: missing worker deployment artifacts.

- [ ] **Step 3: Implement `deploy-worker.sh`**

Mirror API preflight/mount semantics, but override image command:

```bash
docker run -d \
  --name ai-recruiter-worker \
  --restart unless-stopped \
  --network ai-recruiter \
  --add-host=host.docker.internal:host-gateway \
  -e "DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/ai_recruiter" \
  -e "AWS_REGION=$AWS_REGION" \
  -e "BEDROCK_AWS_PROFILE=ai-recruiter-bedrock" \
  -e "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
  -e "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
  -v "$HOST_AWS_CONFIG:/root/.aws/config:ro" \
  -v "$HOST_SIGNING_HELPER:/usr/local/bin/aws_signing_helper:ro" \
  -v "$HOST_CLIENT_CRT:/run/rolesanywhere/client.crt:ro" \
  -v "$HOST_CLIENT_KEY:/run/rolesanywhere/client.key:ro" \
  "$ECR_IMAGE" python -m app.workers.candidate_imports
```

- [ ] **Step 4: Extend deploy workflow**

After migration/runtime config availability, deploy worker using the same `${{ github.sha }}` backend image and validate `running`, SHA tag, mounts, and environment. Preserve previous worker image as rollback tag before replacement.

- [ ] **Step 5: Run deploy-contract suite**

Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit deployment slice**

```bash
git add scripts/deploy-worker.sh .github/workflows/deploy.yml app/tests/test_deploy_contract.py
git commit -m "ci: deploy candidate import worker"
```

---

### Task 11: Build frontend import API and resumable upload/polling hook

**Files:**
- Create: `frontend-react/src/features/candidate-import/api.js`
- Create: `frontend-react/src/features/candidate-import/useCandidateImport.js`
- Create: `frontend-react/src/__tests__/candidate-import.test.jsx`

**Interfaces:**
- `createImportBatch(jobId, files)`.
- `uploadToPresignedPost(file, descriptor, onProgress)` using `XMLHttpRequest` so byte progress is real.
- `completeImportBatch(batchId)`.
- `getImportBatch(batchId)`, `getImportItems(batchId, page)`, `getRecentImport(jobId)`.
- Hook returns `{ phase, batch, items, uploadProgress, error, startImport, resumeImport, reset }`.

- [ ] **Step 1: Write failing API/hook tests**

```jsx
it("stops polling at a terminal batch and never invents aggregate progress", async () => {
  vi.useFakeTimers();
  mockGetImportBatch
    .mockResolvedValueOnce({ status: "PROCESSING", current_stage: "EVALUATING", evaluated_items: 2, successful_items: 10 })
    .mockResolvedValueOnce({ status: "COMPLETED", current_stage: "COMPLETED", evaluated_items: 10, successful_items: 10 });
  const { result } = renderHook(() => useCandidateImport());
  await act(() => result.current.resumeImport("batch-1"));
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(result.current.batch.status).toBe("COMPLETED");
  expect(result.current).not.toHaveProperty("overallPercent");
});
```

Add upload-progress, hidden-tab backoff, error, and reload/recent-batch tests.

- [ ] **Step 2: Run frontend test and observe RED**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: module import failure.

- [ ] **Step 3: Implement API helper**

Use existing Axios client for backend calls. Use `XMLHttpRequest` for direct S3 form POST:

```javascript
export function uploadToPresignedPost(file, descriptor, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", descriptor.url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`S3 upload failed: ${xhr.status}`)));
    xhr.onerror = () => reject(new Error("S3 upload failed"));
    const form = new FormData();
    Object.entries(descriptor.fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", file);
    xhr.send(form);
  });
}
```

- [ ] **Step 4: Implement hook with real-stage state**

Start sequence: create batch -> upload all top-level files with bounded browser concurrency -> complete batch -> poll. Poll every 2 s foreground and slower when `document.hidden`; stop on terminal statuses. Persist only `batch_id` as convenience, but recover authoritative active/recent batch from backend.

- [ ] **Step 5: Run frontend hook tests**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: PASS.

- [ ] **Step 6: Commit frontend state slice**

```bash
git add frontend-react/src/features/candidate-import/api.js frontend-react/src/features/candidate-import/useCandidateImport.js frontend-react/src/__tests__/candidate-import.test.jsx
git commit -m "feat: add resumable candidate import frontend state"
```

---

### Task 12: Build ASIATI import modal, animated real progress, and Candidates integration

**Files:**
- Create: `frontend-react/src/features/candidate-import/CandidateImportModal.jsx`
- Create: `frontend-react/src/features/candidate-import/ImportProgress.jsx`
- Create: `frontend-react/src/features/candidate-import/ImportSummary.jsx`
- Create: `frontend-react/src/features/candidate-import/candidate-import.css`
- Modify: `frontend-react/src/pages/Candidates.jsx`
- Modify: `frontend-react/src/__tests__/candidate-import.test.jsx`

**Interfaces:**
- `CandidateImportModal({ open, jobs, initialJobId, onClose, onCompleted })`.
- Stage components consume persisted batch counters only.

- [ ] **Step 1: Add failing UX tests**

```jsx
it("renders measurable evaluation progress and indeterminate ingestion without fake total percent", () => {
  render(<ImportProgress batch={{ status: "PROCESSING", current_stage: "EVALUATING", evaluated_items: 143, successful_items: 327 }} />);
  expect(screen.getByText(/143 \/ 327/)).toBeInTheDocument();
  expect(screen.queryByText(/68%/)).not.toBeInTheDocument();
});

it("marks ingestion as indeterminate", () => {
  render(<ImportProgress batch={{ status: "PROCESSING", current_stage: "INGESTING" }} />);
  expect(screen.getByTestId("indeterminate-progress")).toBeInTheDocument();
});
```

Add tests for PDF/DOCX/ZIP acceptance, 500 direct-document ceiling, 15 MiB direct-doc limit, terminal summaries, `Ver ranking`, and reduced-motion class/media rule.

- [ ] **Step 2: Run UX tests and observe RED**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: missing component imports.

- [ ] **Step 3: Implement modal and stage components**

Modal accepts `.pdf,.docx,.zip`, requires a job, shows top-level file upload progress by bytes, then swaps to persisted async pipeline view without closing automatically. Terminal summary shows created/reused/failed/evaluation-failed counts and ranking action when `ranking_ready` is true.

- [ ] **Step 4: Add motion CSS with reduced-motion override**

```css
.import-progress__fill {
  transition: width 240ms ease;
}
.import-stage--active {
  animation: importPulse 1.4s ease-in-out infinite;
}
@keyframes importPulse {
  0%, 100% { opacity: 0.62; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .import-progress__fill,
  .import-stage,
  .import-row {
    transition: none !important;
    animation: none !important;
  }
}
```

Use existing ASIATI CSS variables/colors; do not replace brand palette.

- [ ] **Step 5: Replace only legacy upload state in `Candidates.jsx`**

Remove `candidateFiles`, `UPLOAD_BATCH_SIZE`, synchronous `/candidates/bulk` calls, and related upload-only handlers. Keep candidate list/evaluate/assign/download behavior. Open `CandidateImportModal` from the existing create action and pass `searchParams.get("job_id")` as initial job; call `loadData()` after terminal completion.

- [ ] **Step 6: Run frontend lint/tests/build**

Run:

```bash
cd frontend-react
npm run lint
npx vitest run
npm run build
```

Expected: all PASS.

- [ ] **Step 7: Commit frontend UX slice**

```bash
git add frontend-react/src/features/candidate-import frontend-react/src/pages/Candidates.jsx frontend-react/src/__tests__/candidate-import.test.jsx
git commit -m "feat: add animated bulk candidate import ux"
```

---

### Task 13: Full regression, PostgreSQL/migration verification, and PR readiness

**Files:**
- Modify only if verification exposes a defect; any fix must begin with a reproducing failing test in the owning task's test file.

**Interfaces:**
- Produces evidence that the feature and all existing contracts are green before PR review.

- [ ] **Step 1: Run full backend SQLite suite**

Run: `python -m pytest app/tests/ -q`

Expected: all tests PASS.

- [ ] **Step 2: Run contract suite explicitly**

Run: `python -m pytest app/tests/test_contract.py -q`

Expected: all contract tests PASS; legacy `/api/candidates/bulk` behavior remains intact.

- [ ] **Step 3: Run PostgreSQL smoke including migration 002 -> 003**

Start the same PostgreSQL service used by CI, point `DATABASE_URL` at it, run:

```bash
alembic -c app/alembic.ini upgrade 002
alembic -c app/alembic.ini upgrade 003
python -m pytest app/tests/ -q
```

Expected: migration and tests PASS against PostgreSQL.

- [ ] **Step 4: Run frontend verification**

```bash
cd frontend-react
npm run lint
npx vitest run
npm run build
```

Expected: PASS.

- [ ] **Step 5: Run architecture/deploy/import focused suites**

```bash
python -m pytest \
  app/tests/test_architecture_boundaries.py \
  app/tests/test_deploy_contract.py \
  app/tests/test_candidate_import_models.py \
  app/tests/test_candidate_import_rules.py \
  app/tests/test_candidate_import_documents.py \
  app/tests/test_candidate_import_infrastructure.py \
  app/tests/test_candidate_import_domain.py \
  app/tests/test_candidate_import_api.py \
  app/tests/test_candidate_import_worker.py \
  app/tests/test_candidate_identity_backfill.py -q
```

Expected: PASS.

- [ ] **Step 6: Compare branch scope against the approved spec**

Run:

```bash
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Expected: only importer, required Ranking helper, deployment/infrastructure, tests, plan/spec, and targeted Candidates integration. No source-origin field, Browser Use, unrelated frontend redesign, or removal of legacy bulk upload.

- [ ] **Step 7: Push branch and open PR only after fresh green evidence**

PR title: `feat: add durable bulk candidate import pipeline`

PR body must include the exact test counts/results from this verification run, AWS resources introduced, migration `003`, rollback notes, and issue `#8` reference.
