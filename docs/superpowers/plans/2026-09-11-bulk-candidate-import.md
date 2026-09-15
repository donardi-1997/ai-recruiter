# Bulk Candidate Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a durable, tenant-safe bulk CV importer for up to 500 PDF/DOCX documents (directly or inside ZIPs) that uploads to S3, deduplicates candidates, performs one logical Bedrock Knowledge Base ingestion per changed batch, evaluates candidates automatically, materializes ranking, and drives an animated progress UI from persisted backend state.

**Architecture:** The browser uploads top-level files directly to a private staging S3 bucket using presigned POSTs. FastAPI persists `ImportBatch`/`ImportItem` state and dispatches only a batch ID through SQS Standard; a separate worker container resumes an idempotent state machine from PostgreSQL, writes canonical candidate documents, waits for Bedrock ingestion, evaluates candidates, and materializes ranking without a second evaluation pass. React polls persisted state and animates only measured progress.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2, Alembic 1.19.2, PostgreSQL, boto3, Amazon S3, Amazon SQS + DLQ, Amazon Bedrock Knowledge Bases, PyMuPDF, python-docx, React/Vite, Axios, Vitest, CSS animations.

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
- Preserve existing Candidate, Evaluation, Job, Ranking, auth, ASIATI branding, and legacy `/api/candidates/bulk` contracts.
- Strict RED -> GREEN TDD; no production implementation is added before its failing test is observed.

---

## File Structure Map

### Backend persistence/domain

- Modify `requirements.txt` — add Alembic runtime pin used by deployment migration.
- Create `app/migrations/versions/003_candidate_imports.py` — additive import schema.
- Modify `app/models.py` — ORM mirrors migration 003.
- Create `app/domains/candidate_imports/{__init__,exceptions,presenter,repository,router,schemas,service,rules}.py` — application boundary.
- Modify `app/domains/candidates/repository.py` — importer-safe candidate metadata helpers.
- Modify `app/domains/ranking/service.py` — ranking materialization from persisted evaluations only.
- Modify `app/bootstrap.py` — include candidate-import router.
- Modify `app/config.py` — import-specific environment getters.

### Infrastructure/worker/scripts

- Create `app/infrastructure/imports/{__init__,storage,queue,documents,ingestion}.py`.
- Create `app/workers/{__init__,candidate_imports}.py`.
- Create `app/scripts/{__init__,backfill_candidate_identities,migrate_candidate_import}.py`.

### AWS/deployment

- Create `infra/candidate-import.yml` — staging bucket, SQS queue/DLQ, resource policies/outputs.
- Create `scripts/deploy-worker.sh` — worker deployment.
- Modify `scripts/deploy-api.sh` — pass import runtime variables to API.
- Modify `.github/workflows/deploy.yml` — provision stack, run migration/backfill, deploy API/worker, verify both.
- Modify `.env.example` — import environment variables.

### Frontend

- Create `frontend-react/src/features/candidate-import/api.js`.
- Create `frontend-react/src/features/candidate-import/useCandidateImport.js`.
- Create `frontend-react/src/features/candidate-import/CandidateImportModal.jsx`.
- Create `frontend-react/src/features/candidate-import/ImportProgress.jsx`.
- Create `frontend-react/src/features/candidate-import/ImportSummary.jsx`.
- Create `frontend-react/src/features/candidate-import/candidate-import.css`.
- Modify `frontend-react/src/pages/Candidates.jsx` — integrate new import feature only.
- Modify `frontend-react/src/pages/Ranking.jsx` — honor `?job_id=` for `Ver ranking` deep link.

### Tests

- Create `app/tests/test_candidate_import_models.py`.
- Create `app/tests/test_candidate_import_rules.py`.
- Create `app/tests/test_candidate_import_documents.py`.
- Create `app/tests/test_candidate_import_infrastructure.py`.
- Create `app/tests/test_candidate_import_domain.py`.
- Create `app/tests/test_candidate_import_api.py`.
- Create `app/tests/test_candidate_import_worker.py`.
- Create `app/tests/test_candidate_identity_backfill.py`.
- Create `app/tests/test_candidate_import_migration.py`.
- Modify `app/tests/test_ranking.py`.
- Modify `app/tests/test_architecture_boundaries.py`.
- Modify `app/tests/test_deploy_contract.py`.
- Create `frontend-react/src/__tests__/candidate-import.test.jsx`.

---

### Task 1: Persist import batches, items, and strong identities

**Files:**
- Modify: `requirements.txt`
- Create: `app/migrations/versions/003_candidate_imports.py`
- Modify: `app/models.py`
- Create: `app/tests/test_candidate_import_models.py`

**Interfaces:**
- Produces `ImportBatch`, `ImportItem`, and `CandidateIdentity` ORM classes.
- Produces `UNIQUE(owner_sub, kind, value)` for strong identities.
- Preserves job deletion with `ImportBatch.job_id ON DELETE CASCADE` and candidate deletion with `ImportItem.candidate_id ON DELETE SET NULL`.

- [ ] **Step 1: Write the failing model tests**

```python
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem, Job


def test_candidate_import_tables_exist():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert {"import_batches", "import_items", "candidate_identities"} <= set(inspect(engine).get_table_names())


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
        with pytest.raises(IntegrityError):
            db.commit()


def test_same_identity_value_is_allowed_for_different_owners():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a = Candidate(name="Ana A", owner_sub="owner-a")
        b = Candidate(name="Ana B", owner_sub="owner-b")
        db.add_all([a, b])
        db.commit()
        db.add_all([
            CandidateIdentity(owner_sub="owner-a", candidate_id=a.id, kind="EMAIL", value="ana@example.com"),
            CandidateIdentity(owner_sub="owner-b", candidate_id=b.id, kind="EMAIL", value="ana@example.com"),
        ])
        db.commit()
        assert db.query(CandidateIdentity).count() == 2
```

- [ ] **Step 2: Run the model tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_models.py -q`

Expected: collection fails because the three import ORM classes do not exist.

- [ ] **Step 3: Add the Alembic runtime dependency and ORM models**

Add `alembic==1.19.2` to `requirements.txt`. Add imports `Boolean`, `UniqueConstraint`, and `Index` to `app/models.py` and implement the fields from the approved spec. `ImportItem` must include:

```python
class ImportItem(Base):
    __tablename__ = "import_items"
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(UUID(as_uuid=False), ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    parent_item_id = Column(UUID(as_uuid=False), ForeignKey("import_items.id", ondelete="CASCADE"), nullable=True)
    kind = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    staging_s3_key = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    document_sha256 = Column(Text, nullable=True)
    candidate_id = Column(UUID(as_uuid=False), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    status = Column(Text, nullable=False, default="UPLOADING")
    current_stage = Column(Text, nullable=False, default="UPLOADING")
    outcome = Column(Text, nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
```

Implement all `ImportBatch` counters/timestamps and `CandidateIdentity` fields exactly as specified in the design document.

- [ ] **Step 4: Create migration `003` and a structural migration test**

`003_candidate_imports.py` has `revision = "003"`, `down_revision = "002"`, creates the three tables, uniqueness/indexes, and drops them in reverse order on downgrade. Extend `test_candidate_import_models.py` with:

```python
def test_migration_003_is_additive_and_points_to_002():
    text = Path("app/migrations/versions/003_candidate_imports.py").read_text(encoding="utf-8")
    assert 'revision = "003"' in text
    assert 'down_revision = "002"' in text
    assert 'op.create_table("import_batches"' in text
    assert 'op.create_table("import_items"' in text
    assert 'op.create_table("candidate_identities"' in text
```

- [ ] **Step 5: Run model tests and Alembic executable check**

Run:

```bash
python -m pytest app/tests/test_candidate_import_models.py -q
python -m alembic --version
```

Expected: tests PASS and Alembic reports `1.19.2` after dependencies are installed.

- [ ] **Step 6: Commit persistence slice**

```bash
git add requirements.txt app/models.py app/migrations/versions/003_candidate_imports.py app/tests/test_candidate_import_models.py
git commit -m "feat: add candidate import persistence model"
```

---

### Task 2: Implement state rules, identity normalization, and safe PDF/DOCX/ZIP parsing

**Files:**
- Create: `app/domains/candidate_imports/__init__.py`
- Create: `app/domains/candidate_imports/rules.py`
- Create: `app/infrastructure/imports/__init__.py`
- Create: `app/infrastructure/imports/documents.py`
- Create: `app/tests/test_candidate_import_rules.py`
- Create: `app/tests/test_candidate_import_documents.py`

**Interfaces:**
- `normalize_email(value: str) -> str`.
- `normalize_phone(value: str) -> str`.
- `document_sha256(data: bytes) -> str`.
- `resolve_identity_candidates(matches: dict[str, str]) -> str | None`.
- `transition_batch(status: str, current_stage: str, next_stage: str) -> tuple[str, str]`.
- `ParsedDocument(filename, content_type, text, header_text, display_name, email, phone, sha256)`.
- `ExpandedDocument(filename, content_type, data)`.
- `extract_document(data: bytes, filename: str) -> ParsedDocument`.
- `expand_zip(data: bytes, *, remaining_documents: int, remaining_bytes: int) -> list[ExpandedDocument]`.

- [ ] **Step 1: Write failing rule/state tests**

```python
import pytest
from app.domains.candidate_imports.rules import IdentityConflict, InvalidTransition, normalize_email, normalize_phone, resolve_identity_candidates, transition_batch


def test_identity_normalization_and_conflict_policy():
    assert normalize_email("  ANA@Example.COM ") == "ana@example.com"
    assert normalize_phone("+57 (300) 123-4567") == "+573001234567"
    assert resolve_identity_candidates({"EMAIL": "c1", "PHONE": "c1"}) == "c1"
    assert resolve_identity_candidates({}) is None
    with pytest.raises(IdentityConflict):
        resolve_identity_candidates({"EMAIL": "c1", "PHONE": "c2"})


def test_terminal_batch_cannot_reactivate():
    with pytest.raises(InvalidTransition):
        transition_batch("COMPLETED", "COMPLETED", "EVALUATING")


def test_processing_stage_transition_keeps_processing_status():
    assert transition_batch("PROCESSING", "DEDUPLICATING", "INGESTING") == ("PROCESSING", "INGESTING")
```

- [ ] **Step 2: Run rule tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_rules.py -q`

Expected: import failure because rules do not exist.

- [ ] **Step 3: Implement the exact rule constants and transitions**

Use:

```python
TERMINAL_BATCH_STATUSES = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}
ACTIVE_STAGES = ("UPLOADING", "VALIDATING", "DEDUPLICATING", "INGESTING", "EVALUATING", "RANKING", "COMPLETED")
ALLOWED_STAGE_NEXT = {
    "UPLOADING": {"VALIDATING"},
    "VALIDATING": {"DEDUPLICATING"},
    "DEDUPLICATING": {"INGESTING", "EVALUATING"},
    "INGESTING": {"EVALUATING"},
    "EVALUATING": {"RANKING"},
    "RANKING": {"COMPLETED"},
    "COMPLETED": set(),
}
```

`transition_batch()` rejects backward/terminal reactivation; `FAILED` retains the stage that failed; successful terminalization sets `current_stage="COMPLETED"`.

- [ ] **Step 4: Write failing document/archive tests**

```python
import io
import zipfile
import pytest
from app.infrastructure.imports.documents import DocumentLimitExceeded, UnsafeArchive, expand_zip, extract_document


def test_extract_pdf_uses_header_contacts_and_filename_fallback(minimal_pdf_bytes):
    parsed = extract_document(minimal_pdf_bytes("Ana Gomez\nana@example.com\n+57 300 123 4567\nBackend Engineer"), "ana_gomez.pdf")
    assert parsed.email == "ana@example.com"
    assert parsed.phone == "+573001234567"
    assert parsed.display_name == "Ana Gomez"
    assert len(parsed.sha256) == 64


def test_expand_zip_rejects_traversal(make_zip, minimal_pdf_bytes):
    payload = make_zip({"../evil.pdf": minimal_pdf_bytes("Ana")})
    with pytest.raises(UnsafeArchive):
        expand_zip(payload, remaining_documents=500, remaining_bytes=1024 * 1024 * 1024)


def test_expand_zip_rejects_nested_archive(make_zip):
    payload = make_zip({"nested.zip": make_zip({"cv.pdf": b"not-read"})})
    with pytest.raises(UnsafeArchive):
        expand_zip(payload, remaining_documents=500, remaining_bytes=1024 * 1024 * 1024)


def test_expand_zip_enforces_document_ceiling(make_zip, minimal_pdf_bytes):
    payload = make_zip({"a.pdf": minimal_pdf_bytes("A"), "b.pdf": minimal_pdf_bytes("B")})
    with pytest.raises(DocumentLimitExceeded):
        expand_zip(payload, remaining_documents=1, remaining_bytes=1024 * 1024 * 1024)
```

Add equivalent DOCX extraction, symlink rejection, malformed ZIP, empty file, 15 MiB document, 500 MiB ZIP declaration, and 1 GiB expanded-size tests in the same file.

- [ ] **Step 5: Run document tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_documents.py -q`

Expected: missing parser functions/types.

- [ ] **Step 6: Implement deterministic extraction and ZIP safety**

For PDF use `fitz.open(stream=data, filetype="pdf")`; for DOCX use `docx.Document(io.BytesIO(data))`. Define header region as the first 40 non-empty lines capped at 4,000 characters. Email/phone becomes a strong identity only when the normalized unique set for that type contains exactly one value. Derive display name by scanning the first eight header lines for the first line with 2–6 word tokens, no `@`, no URL, no digits, and not the labels `cv`, `curriculum vitae`, or `hoja de vida`; otherwise normalize the filename stem by replacing `_`/`-` with spaces.

ZIP processing must reject absolute paths, `..`, symlinks, and nested archive suffixes and ignore non-document metadata files. Use this exact safety gate:

```python
path = PurePosixPath(info.filename)
mode = (info.external_attr >> 16) & 0o170000
if path.is_absolute() or ".." in path.parts:
    raise UnsafeArchive("UNSAFE_ARCHIVE_PATH")
if mode == 0o120000:
    raise UnsafeArchive("ARCHIVE_SYMLINK")
if path.suffix.lower() in {".zip", ".tar", ".gz", ".rar", ".7z"}:
    raise UnsafeArchive("NESTED_ARCHIVE")
```

- [ ] **Step 7: Run rule/document tests**

Run: `python -m pytest app/tests/test_candidate_import_rules.py app/tests/test_candidate_import_documents.py -q`

Expected: PASS.

- [ ] **Step 8: Commit deterministic rules/parsing slice**

```bash
git add app/domains/candidate_imports app/infrastructure/imports app/tests/test_candidate_import_rules.py app/tests/test_candidate_import_documents.py
git commit -m "feat: add candidate import parsing and state rules"
```

---

### Task 3: Add import configuration and AWS storage/queue/ingestion adapters

**Files:**
- Modify: `app/config.py`
- Create: `app/infrastructure/imports/storage.py`
- Create: `app/infrastructure/imports/queue.py`
- Create: `app/infrastructure/imports/ingestion.py`
- Create: `app/tests/test_candidate_import_infrastructure.py`
- Modify: `app/tests/test_config.py`
- Modify: `.env.example`

**Interfaces:**
- `create_staging_presigned_post(*, batch_id: str, item_id: str, content_type: str, size_bytes: int) -> dict`.
- `head_staging_object(key: str) -> dict`.
- `read_staging_object(key: str) -> bytes`.
- `write_staging_child(*, batch_id: str, item_id: str, filename: str, data: bytes, content_type: str) -> str`.
- `delete_staging_prefix(batch_id: str) -> None`.
- `write_canonical_candidate_document(*, candidate_id: str, candidate_name: str, filename: str, data: bytes, sha256: str) -> CanonicalWriteResult`.
- `send_import_batch(batch_id: str) -> None`.
- `receive_import_messages() -> list[ReceivedImportMessage]` including receipt handle and receive count.
- `delete_message(receipt_handle: str) -> None`.
- `extend_visibility(receipt_handle: str, seconds: int) -> None`.
- `start_batch_ingestion(batch_id: str) -> tuple[str, str]`.
- `get_ingestion_status(job_id: str) -> str`.

- [ ] **Step 1: Write failing adapter tests**

```python
import json
from app.infrastructure.imports import ingestion, queue, storage


def test_sqs_message_contains_only_schema_and_batch_id(fake_sqs, monkeypatch):
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake_sqs)
    queue.send_import_batch("batch-1")
    assert json.loads(fake_sqs.sent[0]["MessageBody"]) == {"schema_version": 1, "batch_id": "batch-1"}


def test_receive_exposes_approximate_receive_count(fake_sqs, monkeypatch):
    fake_sqs.messages = [{"Body": '{"schema_version":1,"batch_id":"b"}', "ReceiptHandle": "rh", "Attributes": {"ApproximateReceiveCount": "5"}}]
    monkeypatch.setattr(queue, "_sqs_client", lambda: fake_sqs)
    message = queue.receive_import_messages()[0]
    assert message.batch_id == "b"
    assert message.receive_count == 5
    assert message.receipt_handle == "rh"


def test_bedrock_start_uses_deterministic_client_token(fake_bedrock, monkeypatch):
    monkeypatch.setattr(ingestion, "_client", lambda: fake_bedrock)
    ingestion.start_batch_ingestion("batch-123")
    assert fake_bedrock.last_request["clientToken"] == ingestion.client_token_for_batch("batch-123")


def test_canonical_write_removes_stale_extension(fake_s3, monkeypatch):
    monkeypatch.setattr(storage, "_s3_client", lambda: fake_s3)
    result = storage.write_canonical_candidate_document(
        candidate_id="c1", candidate_name="Ana", filename="ana.docx", data=b"docx", sha256="a" * 64
    )
    assert result.changed is True
    assert result.key == "documents/cv-c1.docx"
    assert "documents/cv-c1.pdf" in fake_s3.deleted_keys
```

- [ ] **Step 2: Run adapter/config tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py -q`

Expected: failures for missing adapters/config getters.

- [ ] **Step 3: Add exact environment getters**

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

`.env.example` also contains `IMPORT_STAGING_BUCKET`, `IMPORT_QUEUE_URL`, `IMPORT_EVALUATION_CONCURRENCY=3`, and `IMPORT_LEASE_TIMEOUT_SECONDS=300`.

- [ ] **Step 4: Implement staging and canonical storage adapters**

Presigned POSTs use a one-hour TTL, fixed object key `imports/{batch_id}/{item_id}/{safe_filename}`, declared content type, and a maximum equal to the declared top-level object size. `complete` will enforce exact `ContentLength` via HEAD. Canonical keys are `documents/cv-{candidate_id}.pdf|docx`; metadata sidecar remains `{canonical_key}.metadata.json` and preserves the canonical `candidate_id` filter. Put S3 metadata `document-sha256=<sha>` so unchanged documents are detected without downloading the canonical object. Delete stale `.pdf`/`.docx` variants when extension changes.

- [ ] **Step 5: Implement SQS and Bedrock adapters**

`receive_message` must request `ApproximateReceiveCount`, use `WaitTimeSeconds=20`, and deserialize only schema version 1. Bedrock token is:

```python
def client_token_for_batch(batch_id: str) -> str:
    return hashlib.sha256(f"candidate-import:{batch_id}".encode("utf-8")).hexdigest()
```

Use the existing Roles Anywhere-backed `_bedrock_session` for S3/SQS/Bedrock clients.

- [ ] **Step 6: Run adapter/config tests**

Run: `python -m pytest app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 7: Commit AWS adapter slice**

```bash
git add app/config.py app/infrastructure/imports .env.example app/tests/test_candidate_import_infrastructure.py app/tests/test_config.py
git commit -m "feat: add candidate import aws adapters"
```

---

### Task 4: Build candidate-import repository and application service

**Files:**
- Create: `app/domains/candidate_imports/exceptions.py`
- Create: `app/domains/candidate_imports/repository.py`
- Create: `app/domains/candidate_imports/schemas.py`
- Create: `app/domains/candidate_imports/presenter.py`
- Create: `app/domains/candidate_imports/service.py`
- Modify: `app/domains/candidates/repository.py`
- Create: `app/tests/test_candidate_import_domain.py`

**Interfaces:**
- `create_batch(db, *, owner_sub: str, job_id: str, uploads: list[dict]) -> tuple[ImportBatch, list[dict]]`.
- `complete_batch_uploads(db, *, owner_sub: str, batch_id: str) -> ImportBatch`.
- `get_batch(db, *, owner_sub: str, batch_id: str) -> ImportBatch`.
- `list_batch_items(db, *, owner_sub: str, batch_id: str, page: int, page_size: int) -> tuple[list[ImportItem], int]`.
- `list_recent_batches(db, *, owner_sub: str, job_id: str, limit: int) -> list[ImportBatch]`.
- `resolve_or_create_candidate(db, *, owner_sub: str, parsed_document: ParsedDocument, batch_id: str) -> tuple[Candidate, str]`.

- [ ] **Step 1: Write failing service tests for ownership, creation, and deduplication**

```python
import pytest
from app.domains.candidate_imports import service
from app.domains.candidate_imports.exceptions import IdentityConflict, JobNotFound
from app.models import Candidate, CandidateIdentity, Job


def test_create_batch_requires_owned_job(db, monkeypatch):
    job = Job(title="Backend", owner_sub="owner-a")
    db.add(job)
    db.commit()
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", lambda **kwargs: {"url": "https://s3", "fields": {"key": kwargs["item_id"]}})
    batch, descriptors = service.create_batch(
        db, owner_sub="owner-a", job_id=job.id,
        uploads=[{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    )
    assert batch.owner_sub == "owner-a"
    assert batch.upload_total == 1
    assert descriptors[0]["upload"]["url"] == "https://s3"
    with pytest.raises(JobNotFound):
        service.create_batch(db, owner_sub="owner-b", job_id=job.id, uploads=[])


def test_name_only_never_reuses_candidate(db, parsed_document_factory):
    existing = Candidate(name="Ana Gomez", email=None, owner_sub="owner-a")
    db.add(existing)
    db.commit()
    candidate, outcome = service.resolve_or_create_candidate(
        db, owner_sub="owner-a", parsed_document=parsed_document_factory(name="Ana Gomez", email=None, phone=None), batch_id="batch-1"
    )
    assert outcome == "CREATED"
    assert candidate.id != existing.id


def test_conflicting_strong_identities_fail_item(db, parsed_document_factory):
    a = Candidate(name="A", owner_sub="owner-a")
    b = Candidate(name="B", owner_sub="owner-a")
    db.add_all([a, b])
    db.commit()
    db.add_all([
        CandidateIdentity(owner_sub="owner-a", candidate_id=a.id, kind="EMAIL", value="ana@example.com"),
        CandidateIdentity(owner_sub="owner-a", candidate_id=b.id, kind="PHONE", value="+573001234567"),
    ])
    db.commit()
    with pytest.raises(IdentityConflict):
        service.resolve_or_create_candidate(
            db, owner_sub="owner-a",
            parsed_document=parsed_document_factory(email="ana@example.com", phone="+573001234567"),
            batch_id="batch-1",
        )
```

- [ ] **Step 2: Run domain tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_domain.py -q`

Expected: missing repository/service/schemas/presenter behavior.

- [ ] **Step 3: Implement owner-scoped repository primitives**

Implement concrete query/create functions using SQLAlchemy. `get_batch()` is exactly:

```python
def get_batch(db: Session, batch_id: str, owner_sub: str) -> ImportBatch | None:
    return (
        db.query(ImportBatch)
        .filter(ImportBatch.id == batch_id, ImportBatch.owner_sub == owner_sub)
        .first()
    )
```

`find_identity()` filters all three identity columns; `attach_identity()` uses `flush()` and on `IntegrityError` rolls back only a nested savepoint, re-reads the identity, returns it when it points to the same candidate, and raises `IdentityConflict` when it points elsewhere. Batch/item list queries are always constrained by `owner_sub` through the parent batch.

- [ ] **Step 4: Implement candidate metadata helper**

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

A reused candidate with a different existing non-empty email is not overwritten.

- [ ] **Step 5: Implement batch creation/completion and strong-identity resolution**

`create_batch()` verifies the job with Jobs repository/service ownership semantics, rejects an empty manifest and more than 500 direct non-ZIP documents, creates one top-level `ImportItem` per selected file, and returns presigned descriptors. `complete_batch_uploads()` HEADs every declared object and requires `ContentLength == item.size_bytes`; it commits `UPLOADING -> QUEUED` with `queue_dispatched_at=None`, sends SQS, then persists dispatch time. If send fails, the batch remains durable `QUEUED` with null dispatch timestamp so retry/worker repair can dispatch it.

`resolve_or_create_candidate()` resolves SHA/email/phone identities, never queries by name, uses the filename/header display-name rule, attaches new unambiguous identities, and idempotently assigns the candidate to the selected job through Candidates repository.

- [ ] **Step 6: Add presenter/schema contract assertions and run tests**

The created response contains `batch_id`, `status`, `current_stage`, `uploads`, `expires_at`; progress response contains only public counters/stage/ranking info and sanitized error fields. Run:

`python -m pytest app/tests/test_candidate_import_domain.py app/tests/test_candidates_domain.py -q`

Expected: PASS.

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
- `POST /api/import-batches` returns 202.
- `POST /api/import-batches/{batch_id}/complete`.
- `GET /api/import-batches/{batch_id}`.
- `GET /api/import-batches/{batch_id}/items?page=1&page_size=100`.
- `GET /api/import-batches?job_id={job_id}&limit=10`.

- [ ] **Step 1: Write failing API ownership/contract tests**

```python
def test_create_batch_returns_202_and_presigned_manifest(client, owned_job_id, monkeypatch):
    monkeypatch.setattr(service.storage, "create_staging_presigned_post", lambda **kwargs: {"url": "https://s3", "fields": {"key": kwargs["item_id"]}})
    response = client.post("/api/import-batches", json={
        "job_id": owned_job_id,
        "uploads": [{"filename": "ana.pdf", "size_bytes": 100, "content_type": "application/pdf"}],
    })
    assert response.status_code == 202
    assert response.json()["status"] == "UPLOADING"


def test_other_owner_cannot_read_batch(client_as_owner_b, batch_for_owner_a):
    response = client_as_owner_b.get(f"/api/import-batches/{batch_for_owner_a.id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Importacion no encontrada."}
```

Also create explicit tests that `/complete` is idempotent, item pagination is owner-scoped, recent batches verify job ownership, and API payloads never contain `staging_s3_key`, queue receipt handles, raw provider exceptions, or presigned fields after creation.

- [ ] **Step 2: Run API tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_api.py -q`

Expected: 404/missing route.

- [ ] **Step 3: Implement HTTP-only router**

```python
router = APIRouter(prefix="/api/import-batches", tags=["candidate-imports"])

@router.post("", status_code=202)
def create_import_batch(body: CreateImportBatchRequest, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        batch, uploads = service.create_batch(
            db, owner_sub=user["sub"], job_id=body.job_id,
            uploads=[item.model_dump() for item in body.uploads],
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return presenter.batch_created_payload(batch, uploads)
```

Map domain not-found to exact public 404 messages and retryable queue dispatch failure to a sanitized 503 while preserving queued state.

- [ ] **Step 4: Add architecture boundary test**

```python
def test_candidate_import_router_uses_application_boundary_only():
    imports = _imports(APP_ROOT / "domains" / "candidate_imports" / "router.py")
    assert "app.crud" not in imports
    assert "app.models" not in imports
    assert not any(name.startswith("app.infrastructure") for name in imports)
    assert not any(name.startswith("app.domains.") and ".repository" in name for name in imports)
```

- [ ] **Step 5: Register router and run HTTP/architecture/bootstrap tests**

Run: `python -m pytest app/tests/test_candidate_import_api.py app/tests/test_architecture_boundaries.py app/tests/test_bootstrap.py -q`

Expected: PASS.

- [ ] **Step 6: Commit HTTP slice**

```bash
git add app/domains/candidate_imports/router.py app/bootstrap.py app/tests/test_candidate_import_api.py app/tests/test_architecture_boundaries.py
git commit -m "feat: expose candidate import batch api"
```

---

### Task 6: Materialize ranking from persisted evaluations without reevaluation

**Files:**
- Modify: `app/domains/ranking/service.py`
- Modify: `app/tests/test_ranking.py`

**Interfaces:**
- `materialize_ranking_from_evaluations(db, *, job_id: str, owner_sub: str, scope: str = "assigned") -> dict[str, Any]`.
- Uses the existing ranking lock and ordering semantics.
- Never calls `evaluate_candidate_for_job`.

- [ ] **Step 1: Add a failing test to existing `test_ranking.py`**

```python
from app.domains.ranking import service as ranking_service


def test_materialize_ranking_uses_persisted_evaluations_only(db_session, monkeypatch):
    job = _seed_job(db_session)
    first = _seed_candidate(db_session, name="Ana")
    second = _seed_candidate(db_session, name="Beto")
    db_session.add_all([
        JobCandidate(job_id=job.id, candidate_id=first.id),
        JobCandidate(job_id=job.id, candidate_id=second.id),
        Evaluation(candidate_id=first.id, job_id=job.id, status="COMPLETED", match_score=90, recommendation="STRONG_MATCH", summary="x" * 120, strengths=[], gaps=[], requirements=[]),
        Evaluation(candidate_id=second.id, job_id=job.id, status="COMPLETED", match_score=70, recommendation="GOOD_MATCH", summary="y" * 120, strengths=[], gaps=[], requirements=[]),
    ])
    db_session.commit()
    monkeypatch.setattr(ranking_service, "evaluate_candidate_for_job", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not evaluate")))
    result = ranking_service.materialize_ranking_from_evaluations(
        db_session, job_id=job.id, owner_sub="test-user-123", scope="assigned"
    )
    assert result["ranking_version"] == 1
    assert result["total_candidates"] == 2
    items = db_session.query(RankingItem).order_by(RankingItem.position).all()
    assert [item.candidate_id for item in items] == [first.id, second.id]
```

- [ ] **Step 2: Run only the new ranking test and observe RED**

Run: `python -m pytest app/tests/test_ranking.py -q -k materialize_ranking_uses_persisted`

Expected: `AttributeError` for missing service function.

- [ ] **Step 3: Implement the no-evaluation materializer**

Reuse current `status_order`, `candidates_repository.list_candidates_for_job`, evaluation lookup, ranking metadata versioning, ordering, `insert_ranking_items`, and existing job lock. Do not call `needs_evaluation()` or evaluation service. Persist `COMPLETED`, `FAILED`, or `PENDING` entries exactly as the current ranking semantics do.

- [ ] **Step 4: Run full ranking tests**

Run: `python -m pytest app/tests/test_ranking.py app/tests/test_locking.py -q`

Expected: PASS.

- [ ] **Step 5: Commit ranking slice**

```bash
git add app/domains/ranking/service.py app/tests/test_ranking.py
git commit -m "feat: materialize ranking from persisted evaluations"
```

---

### Task 7: Implement resumable SQS worker and async pipeline

**Files:**
- Create: `app/workers/__init__.py`
- Create: `app/workers/candidate_imports.py`
- Modify: `app/domains/candidate_imports/repository.py`
- Modify: `app/domains/candidate_imports/service.py`
- Create: `app/tests/test_candidate_import_worker.py`

**Interfaces:**
- `process_batch(batch_id: str, *, receipt_handle: str | None = None) -> None`.
- `run_worker_forever() -> None`.
- `claim_batch(db, *, batch_id: str, token: str, now: datetime, lease_seconds: int) -> bool`.
- `heartbeat_batch(db, *, batch_id: str, token: str, now: datetime) -> None`.
- `dispatch_undispatched_batches(db) -> int`.

- [ ] **Step 1: Write failing claim/resume/queue tests**

```python
from datetime import datetime, timedelta, timezone


def test_duplicate_delivery_cannot_claim_fresh_lease(db, queued_batch):
    now = datetime.now(timezone.utc)
    assert repository.claim_batch(db, batch_id=queued_batch.id, token="worker-a", now=now, lease_seconds=300)
    assert not repository.claim_batch(db, batch_id=queued_batch.id, token="worker-b", now=now + timedelta(seconds=30), lease_seconds=300)
    assert repository.claim_batch(db, batch_id=queued_batch.id, token="worker-b", now=now + timedelta(seconds=301), lease_seconds=300)


def test_worker_repairs_queued_batch_without_dispatch_timestamp(db, queued_batch, monkeypatch):
    queued_batch.queue_dispatched_at = None
    db.commit()
    sent = []
    monkeypatch.setattr(worker.queue, "send_import_batch", lambda batch_id: sent.append(batch_id))
    assert worker.dispatch_undispatched_batches(db) == 1
    assert sent == [queued_batch.id]


def test_deleted_batch_message_is_acknowledged(monkeypatch):
    deleted = []
    monkeypatch.setattr(worker, "process_batch", lambda batch_id, receipt_handle=None: worker.BatchMissing())
    monkeypatch.setattr(worker.queue, "delete_message", lambda handle: deleted.append(handle))
    worker.handle_message(ReceivedImportMessage(batch_id="missing", receipt_handle="rh", receive_count=1))
    assert deleted == ["rh"]
```

Add an explicit fifth-receive test asserting a retryable unhandled failure marks the batch `FAILED` with sanitized error before leaving the message unacknowledged for DLQ redrive.

- [ ] **Step 2: Run worker tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_worker.py -q`

Expected: missing worker and lease functions.

- [ ] **Step 3: Implement DB lease and visibility heartbeat keeper**

Use one atomic SQLAlchemy `UPDATE` constrained to non-terminal batches whose `processing_token` is null or `heartbeat_at < now - lease_timeout`. `LeaseKeeper` runs on a daemon thread every 60 seconds while a message is active and performs both DB heartbeat and `queue.extend_visibility(receipt_handle, 300)`; it stops/join()s in a `finally` block.

- [ ] **Step 4: Implement resumable validation/preparation**

For direct documents, parse and prepare the existing staging object. For an archive, expand it once, write every child back to durable staging with `write_staging_child()`, create child `DOCUMENT` rows pointing at those new keys, mark the archive container complete, then process children normally. This guarantees a worker crash after ZIP expansion can resume without reopening/re-expanding the ZIP.

Each successful document computes identities, resolves/creates candidate, idempotently assigns it to the job, writes canonical CV only for the first canonical update for that candidate in the batch, and checkpoints `document_sha256`, candidate, outcome, counters, and item terminal state. An item `IDENTITY_CONFLICT` fails only that item.

- [ ] **Step 5: Implement one logical Bedrock ingestion stage**

If zero canonical documents changed, skip directly from `DEDUPLICATING` to `EVALUATING`. Otherwise start one ingestion with deterministic client token, persist `bedrock_ingestion_job_id`, and poll that same job after restart. Treat `COMPLETE` as success and provider terminal failure/timeout as fatal batch failure; show no synthetic document percentage.

- [ ] **Step 6: Implement bounded, resumable evaluation**

Evaluation candidates are unique candidate IDs from successful items. Before calling the LLM, load the persisted evaluation and strong hash identity. Skip a complete evaluation only when the document hash identity predates the batch; reevaluate when no complete evaluation exists or the imported document hash identity was created during this batch. Use `ThreadPoolExecutor(max_workers=get_import_evaluation_concurrency())`, a fresh `SessionLocal()` per task, and `evaluate_candidate_for_owner()`.

Retry only when `internal_error` contains one of `ThrottlingException`, `TooManyRequestsException`, `ServiceUnavailableException`, `ModelTimeoutException`, or `InternalServerException`; use delays 1s, 2s, 4s and stop after three retries. Each candidate increments `evaluated_items` exactly once when a terminal result is persisted; failed terminal evaluations also increment `evaluation_failed_items`.

- [ ] **Step 7: Implement ranking and terminalization**

Call `materialize_ranking_from_evaluations(..., scope="assigned")`. Persist returned ranking version and `ranking_ready=True`. Set `COMPLETED_WITH_ERRORS` when `failed_items > 0` or `evaluation_failed_items > 0`; otherwise `COMPLETED`. If no document is successfully prepared, job becomes unavailable, required ingestion fatally fails, or ranking cannot be persisted after retry policy, set `FAILED` with public-safe error code/message and retain the failed stage.

- [ ] **Step 8: Run worker/domain/evaluation/ranking tests**

Run:

```bash
python -m pytest app/tests/test_candidate_import_worker.py app/tests/test_candidate_import_domain.py app/tests/test_evaluations_domain.py app/tests/test_ranking.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit worker slice**

```bash
git add app/workers app/domains/candidate_imports app/tests/test_candidate_import_worker.py
git commit -m "feat: add resumable candidate import worker"
```

---

### Task 8: Backfill identities for candidates that predate import V1

**Files:**
- Create: `app/scripts/__init__.py`
- Create: `app/scripts/backfill_candidate_identities.py`
- Create: `app/tests/test_candidate_identity_backfill.py`

**Interfaces:**
- `backfill_candidate_identities(db: Session) -> dict[str, int]`.
- CLI: `python -m app.scripts.backfill_candidate_identities`.

- [ ] **Step 1: Write failing collision/idempotency tests**

```python
def test_backfill_skips_ambiguous_email_collision(db, monkeypatch):
    db.add_all([
        Candidate(name="Ana 1", email="ANA@example.com", owner_sub="owner-a"),
        Candidate(name="Ana 2", email="ana@example.com", owner_sub="owner-a"),
    ])
    db.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: None)
    result = backfill.backfill_candidate_identities(db)
    assert result["email_conflicts"] == 1
    assert db.query(CandidateIdentity).filter_by(owner_sub="owner-a", kind="EMAIL", value="ana@example.com").count() == 0


def test_backfill_is_idempotent(db, monkeypatch):
    candidate = Candidate(name="Beto", email="beto@example.com", owner_sub="owner-a")
    db.add(candidate)
    db.commit()
    monkeypatch.setattr(backfill, "read_existing_canonical_document", lambda candidate_id: b"same-cv")
    backfill.backfill_candidate_identities(db)
    backfill.backfill_candidate_identities(db)
    assert db.query(CandidateIdentity).filter_by(candidate_id=candidate.id).count() == 2
```

- [ ] **Step 2: Run backfill tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_identity_backfill.py -q`

Expected: missing module/function.

- [ ] **Step 3: Implement owner-by-owner safe backfill**

Skip candidates with null owner. Group normalized emails by `(owner_sub, normalized_email)` and seed only groups with one candidate. Read the existing canonical `.pdf` or `.docx` via storage helper when available and seed `DOCUMENT_SHA256`. Never invent phone identities. On uniqueness race re-read and count as idempotent when same candidate, or conflict when different candidate. Logs contain counts/candidate IDs only.

- [ ] **Step 4: Run backfill tests**

Run: `python -m pytest app/tests/test_candidate_identity_backfill.py -q`

Expected: PASS.

- [ ] **Step 5: Commit backfill slice**

```bash
git add app/scripts app/tests/test_candidate_identity_backfill.py
git commit -m "feat: backfill strong candidate identities"
```

---

### Task 9: Provision staging S3, SQS queue/DLQ, and resource-scoped runtime access

**Files:**
- Create: `infra/candidate-import.yml`
- Modify: `app/tests/test_deploy_contract.py`

**Interfaces:**
- Stack name: `ai-recruiter-candidate-import`.
- Parameter: `RuntimeRoleArn` for the existing `AiRecruiterBedrockRuntimeRole`.
- Outputs: `ImportStagingBucket`, `ImportQueueUrl`, `ImportQueueArn`, `ImportDlqUrl`.
- SQS long polling 20 seconds and redrive `maxReceiveCount=5`.

- [ ] **Step 1: Write failing CloudFormation contract tests**

```python
def test_candidate_import_template_has_private_bucket_and_dlq():
    template = yaml.safe_load(Path("infra/candidate-import.yml").read_text())
    resources = template["Resources"]
    queue = resources["ImportQueue"]["Properties"]
    assert queue["ReceiveMessageWaitTimeSeconds"] == 20
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 5
    public = resources["ImportStagingBucket"]["Properties"]["PublicAccessBlockConfiguration"]
    assert public == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    assert resources["ImportStagingBucket"]["Properties"]["LifecycleConfiguration"]["Rules"][0]["ExpirationInDays"] == 1
```

- [ ] **Step 2: Run deploy-contract tests and observe RED**

Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: file-not-found for the new template.

- [ ] **Step 3: Create the stack template**

Define `AWS::S3::Bucket`, `AWS::S3::BucketPolicy`, DLQ, main `AWS::SQS::Queue`, and `AWS::SQS::QueuePolicy`. Bucket policy grants the supplied runtime role only `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, and `s3:ListBucket` on the staging bucket. Queue policy grants only `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, and `sqs:GetQueueAttributes` on the import queue. No S3/SQS statement uses `Resource: "*"`.

CORS allows POST/HEAD from `https://ai.adrianguerra.net` and the explicit dev origins already listed in `app.config.CORS_ORIGINS`; lifecycle deletes staging objects after one day; server-side encryption and Block Public Access are enabled.

- [ ] **Step 4: Add resource-scope assertions and run deploy tests**

Add assertions that `RuntimeRoleArn` is used as policy principal and outputs exist. Run: `python -m pytest app/tests/test_deploy_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit infrastructure slice**

```bash
git add infra/candidate-import.yml app/tests/test_deploy_contract.py
git commit -m "infra: provision candidate import queue and staging bucket"
```

---

### Task 10: Make production migration/backfill safe and deploy API + worker from one immutable image

**Files:**
- Create: `app/scripts/migrate_candidate_import.py`
- Create: `app/tests/test_candidate_import_migration.py`
- Create: `scripts/deploy-worker.sh`
- Modify: `scripts/deploy-api.sh`
- Modify: `.github/workflows/deploy.yml`
- Modify: `app/tests/test_deploy_contract.py`

**Interfaces:**
- `python -m app.scripts.migrate_candidate_import` safely adopts/updates live DB to `003`.
- Worker container: `ai-recruiter-worker`.
- Worker command: `python -m app.workers.candidate_imports`.
- API and worker both receive `IMPORT_STAGING_BUCKET` and `IMPORT_QUEUE_URL`.

- [ ] **Step 1: Write failing migration preflight tests**

```python
def test_existing_schema_without_alembic_version_is_stamped_then_upgraded(monkeypatch):
    calls = []
    monkeypatch.setattr(migrate, "database_has_current_baseline", lambda: True)
    monkeypatch.setattr(migrate, "get_current_revision", lambda: None)
    monkeypatch.setattr(migrate, "stamp", lambda revision: calls.append(("stamp", revision)))
    monkeypatch.setattr(migrate, "upgrade", lambda revision: calls.append(("upgrade", revision)))
    migrate.ensure_candidate_import_schema()
    assert calls == [("stamp", "002"), ("upgrade", "003")]


def test_unknown_or_incomplete_baseline_aborts_without_stamp(monkeypatch):
    monkeypatch.setattr(migrate, "database_has_current_baseline", lambda: False)
    monkeypatch.setattr(migrate, "get_current_revision", lambda: None)
    with pytest.raises(RuntimeError, match="baseline"):
        migrate.ensure_candidate_import_schema()
```

`database_has_current_baseline()` requires existing `candidates.owner_sub`, `jobs.owner_sub`, and `evaluations.requirements` columns before a one-time `stamp 002`; this prevents blindly stamping an incompatible DB.

- [ ] **Step 2: Run migration/deploy tests and observe RED**

Run: `python -m pytest app/tests/test_candidate_import_migration.py app/tests/test_deploy_contract.py -q`

Expected: missing migration helper and worker deploy artifacts.

- [ ] **Step 3: Implement migration helper with Alembic API**

If revision is already `003`, no-op. If revision is `002`, upgrade to `003`. If no Alembic revision table but the known current production baseline columns exist, stamp `002` then upgrade `003`. Any other revision/baseline aborts before deployment. Do not downgrade production automatically.

- [ ] **Step 4: Implement worker deploy script and API import env propagation**

`deploy-worker.sh` mirrors API Roles Anywhere preflight/mounts and runs:

```bash
docker run -d \
  --name ai-recruiter-worker \
  --restart unless-stopped \
  --network ai-recruiter \
  --add-host=host.docker.internal:host-gateway \
  -e "DATABASE_URL=$DATABASE_URL" \
  -e "AWS_REGION=$AWS_REGION" \
  -e "BEDROCK_AWS_PROFILE=ai-recruiter-bedrock" \
  -e "IMPORT_STAGING_BUCKET=$IMPORT_STAGING_BUCKET" \
  -e "IMPORT_QUEUE_URL=$IMPORT_QUEUE_URL" \
  -e "IMPORT_EVALUATION_CONCURRENCY=3" \
  -v "$HOST_AWS_CONFIG:/root/.aws/config:ro" \
  -v "$HOST_SIGNING_HELPER:/usr/local/bin/aws_signing_helper:ro" \
  -v "$HOST_CLIENT_CRT:/run/rolesanywhere/client.crt:ro" \
  -v "$HOST_CLIENT_KEY:/run/rolesanywhere/client.key:ro" \
  "$ECR_IMAGE" python -m app.workers.candidate_imports
```

Modify API deploy script to require/pass the same staging bucket and queue URL.

- [ ] **Step 5: Extend CI/CD in safe order**

The production job executes this order:

```bash
aws cloudformation deploy \
  --stack-name ai-recruiter-candidate-import \
  --template-file infra/candidate-import.yml \
  --parameter-overrides RuntimeRoleArn="$AI_RECRUITER_RUNTIME_ROLE_ARN" \
  --no-fail-on-empty-changeset

IMPORT_STAGING_BUCKET=$(aws cloudformation describe-stacks --stack-name ai-recruiter-candidate-import --query "Stacks[0].Outputs[?OutputKey=='ImportStagingBucket'].OutputValue" --output text)
IMPORT_QUEUE_URL=$(aws cloudformation describe-stacks --stack-name ai-recruiter-candidate-import --query "Stacks[0].Outputs[?OutputKey=='ImportQueueUrl'].OutputValue" --output text)
```

Then, using the newly built immutable backend SHA image and production DB/network, run `python -m app.scripts.migrate_candidate_import`, run `python -m app.scripts.backfill_candidate_identities`, deploy API, deploy worker, and finally frontend. Migration/backfill failure aborts before replacing the running API/worker.

- [ ] **Step 6: Add deploy-contract assertions**

Tests assert workflow order `cloudformation -> migration -> backfill -> API -> worker`, same SHA image for API/worker, worker `running`, Roles Anywhere mounts, import env vars, rollback tag preservation, and no worker deployment on pull-request events.

- [ ] **Step 7: Run migration/deploy tests**

Run: `python -m pytest app/tests/test_candidate_import_migration.py app/tests/test_deploy_contract.py -q`

Expected: PASS.

- [ ] **Step 8: Commit production delivery slice**

```bash
git add app/scripts/migrate_candidate_import.py app/tests/test_candidate_import_migration.py scripts/deploy-worker.sh scripts/deploy-api.sh .github/workflows/deploy.yml app/tests/test_deploy_contract.py
git commit -m "ci: migrate and deploy candidate import worker"
```

---

### Task 11: Build frontend import API and resumable upload/polling hook

**Files:**
- Create: `frontend-react/src/features/candidate-import/api.js`
- Create: `frontend-react/src/features/candidate-import/useCandidateImport.js`
- Create: `frontend-react/src/__tests__/candidate-import.test.jsx`

**Interfaces:**
- `createImportBatch(jobId, files)`.
- `uploadToPresignedPost(file, descriptor, onProgress)`.
- `completeImportBatch(batchId)`.
- `getImportBatch(batchId)`, `getImportItems(batchId, page, pageSize)`, `getRecentImports(jobId)`.
- Hook returns `{ phase, batch, items, uploadProgress, error, startImport, resumeImport, reset }`.

- [ ] **Step 1: Write failing API/hook tests**

```jsx
it("stops polling when the server reaches a terminal status", async () => {
  vi.useFakeTimers();
  mockGetImportBatch
    .mockResolvedValueOnce({ status: "PROCESSING", current_stage: "EVALUATING", evaluated_items: 2, successful_items: 10 })
    .mockResolvedValueOnce({ status: "COMPLETED", current_stage: "COMPLETED", evaluated_items: 10, successful_items: 10 });
  const { result } = renderHook(() => useCandidateImport());
  await act(async () => result.current.resumeImport("batch-1"));
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(result.current.batch.status).toBe("COMPLETED");
  expect(mockGetImportBatch).toHaveBeenCalledTimes(2);
  expect(result.current).not.toHaveProperty("overallPercent");
});

it("uses slower polling while document is hidden", async () => {
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  const { result } = renderHook(() => useCandidateImport());
  await act(async () => result.current.resumeImport("batch-1"));
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(mockGetImportBatch).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(8000));
  expect(mockGetImportBatch).toHaveBeenCalledTimes(2);
});
```

Add an XHR mock test that asserts byte progress uses `loaded/total`, and a recovery test where `getRecentImports(jobId)` finds an active batch after remount.

- [ ] **Step 2: Run hook tests and observe RED**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: missing feature modules.

- [ ] **Step 3: Implement API helper with real S3 upload progress**

```javascript
export function uploadToPresignedPost(file, descriptor, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", descriptor.url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300
      ? resolve()
      : reject(new Error(`S3 upload failed: ${xhr.status}`));
    xhr.onerror = () => reject(new Error("S3 upload failed"));
    const form = new FormData();
    Object.entries(descriptor.fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", file);
    xhr.send(form);
  });
}
```

Backend API calls use the existing Axios client.

- [ ] **Step 4: Implement hook lifecycle**

Use browser upload concurrency 4. Aggregate upload percentage is bytes uploaded / total declared top-level bytes only during `UPLOADING`. After `/complete`, remove aggregate percentage and use backend stage/counters. Poll every 2 seconds in foreground, every 10 seconds when hidden, and stop at `COMPLETED`, `COMPLETED_WITH_ERRORS`, or `FAILED`. Persist the current `batch_id` only as a convenience; backend recent-batch lookup is authoritative after remount/login.

- [ ] **Step 5: Run hook tests**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: PASS.

- [ ] **Step 6: Commit frontend state slice**

```bash
git add frontend-react/src/features/candidate-import/api.js frontend-react/src/features/candidate-import/useCandidateImport.js frontend-react/src/__tests__/candidate-import.test.jsx
git commit -m "feat: add resumable candidate import frontend state"
```

---

### Task 12: Build ASIATI import modal, real-progress animations, and ranking deep link

**Files:**
- Create: `frontend-react/src/features/candidate-import/CandidateImportModal.jsx`
- Create: `frontend-react/src/features/candidate-import/ImportProgress.jsx`
- Create: `frontend-react/src/features/candidate-import/ImportSummary.jsx`
- Create: `frontend-react/src/features/candidate-import/candidate-import.css`
- Modify: `frontend-react/src/pages/Candidates.jsx`
- Modify: `frontend-react/src/pages/Ranking.jsx`
- Modify: `frontend-react/src/__tests__/candidate-import.test.jsx`

**Interfaces:**
- `CandidateImportModal({ open, jobs, initialJobId, onClose, onCompleted })`.
- `Ver ranking` navigates to `/ranking?job_id={selectedJobId}`.

- [ ] **Step 1: Add failing progress/format/deep-link tests**

```jsx
it("renders evaluation count and indeterminate ingestion without a fake overall percent", () => {
  render(<ImportProgress batch={{ status: "PROCESSING", current_stage: "EVALUATING", evaluated_items: 143, successful_items: 327 }} />);
  expect(screen.getByText(/143 \/ 327/)).toBeInTheDocument();
  expect(screen.queryByText(/68%/)).not.toBeInTheDocument();
  rerender(<ImportProgress batch={{ status: "PROCESSING", current_stage: "INGESTING" }} />);
  expect(screen.getByTestId("indeterminate-progress")).toBeInTheDocument();
});

it("accepts pdf docx and zip but rejects unsupported direct files", () => {
  expect(validateSelectedFile(new File(["x"], "a.pdf", { type: "application/pdf" }))).toBeNull();
  expect(validateSelectedFile(new File(["x"], "a.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }))).toBeNull();
  expect(validateSelectedFile(new File(["x"], "a.zip", { type: "application/zip" }))).toBeNull();
  expect(validateSelectedFile(new File(["x"], "a.txt", { type: "text/plain" }))).toMatch(/PDF, DOCX o ZIP/);
});
```

Add tests for 15 MiB direct-doc limit, max 500 direct docs, terminal summaries, `COMPLETED_WITH_ERRORS`, ranking link job ID, and reduced-motion stylesheet rule.

- [ ] **Step 2: Run UX tests and observe RED**

Run: `cd frontend-react && npx vitest run src/__tests__/candidate-import.test.jsx`

Expected: missing components/validation helpers.

- [ ] **Step 3: Implement modal and progress/summary components**

Modal requires a job before start, accepts `.pdf,.docx,.zip`, keeps processing visible after upload, and may be closed without cancelling backend work. `ImportProgress` renders measured document/evaluation counters and indeterminate ingestion/ranking states. `ImportSummary` renders created/reused/failed/evaluation-failed counts and a ranking action only when `ranking_ready` is true.

- [ ] **Step 4: Add ASIATI-compatible motion and reduced-motion override**

```css
.import-progress__fill { transition: width 240ms ease; }
.import-stage--active { animation: importPulse 1.4s ease-in-out infinite; }
@keyframes importPulse {
  0%, 100% { opacity: .62; }
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

Use existing ASIATI CSS variables/colors; do not introduce a replacement brand palette.

- [ ] **Step 5: Integrate the feature into Candidates and ranking query selection**

Remove upload-only state/functions (`candidateFiles`, `UPLOAD_BATCH_SIZE`, synchronous `/candidates/bulk` loop) from `Candidates.jsx` while preserving list/evaluate/assign/download behavior and the legacy backend endpoint. Open the new modal from the existing create action and pass `searchParams.get("job_id")` as initial job. `onCompleted` refreshes candidates.

In `Ranking.jsx`, use `useSearchParams()`; if a valid `job_id` exists among loaded jobs, choose it instead of the first job and call `loadRanking()` for it. This makes `Ver ranking` land on the completed import's vacancy.

- [ ] **Step 6: Run frontend lint/tests/build**

```bash
cd frontend-react
npm run lint
npx vitest run
npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit frontend UX slice**

```bash
git add frontend-react/src/features/candidate-import frontend-react/src/pages/Candidates.jsx frontend-react/src/pages/Ranking.jsx frontend-react/src/__tests__/candidate-import.test.jsx
git commit -m "feat: add animated bulk candidate import ux"
```

---

### Task 13: Full regression, PostgreSQL migration smoke, and PR readiness

**Files:**
- Modify only if fresh verification exposes a defect; every defect fix starts with a reproducing failing test in the owning test file.

**Interfaces:**
- Produces fresh evidence required before claiming completion or opening a ready-for-review PR.

- [ ] **Step 1: Run full backend SQLite suite**

Run: `python -m pytest app/tests/ -q`

Expected: all tests PASS.

- [ ] **Step 2: Run legacy/public contract suite explicitly**

Run: `python -m pytest app/tests/test_contract.py -q`

Expected: PASS, including unchanged `/api/candidates/bulk` contract.

- [ ] **Step 3: Run PostgreSQL additive migration smoke**

Against the CI PostgreSQL service, create the current application schema, remove only the three import tables, stamp the database at `002`, then run `003`:

```bash
python -c "from app.db import Base, get_engine; from app import models; Base.metadata.create_all(get_engine()); e=get_engine(); e.begin().__enter__().exec_driver_sql('DROP TABLE IF EXISTS candidate_identities CASCADE; DROP TABLE IF EXISTS import_items CASCADE; DROP TABLE IF EXISTS import_batches CASCADE')"
python -m alembic -c app/alembic.ini stamp 002
python -m alembic -c app/alembic.ini upgrade 003
python -m pytest app/tests/test_candidate_import_models.py app/tests/test_candidate_import_migration.py -q
```

If the one-line setup proves awkward in CI, replace it with an equivalent checked-in test helper before merging; do not skip the PostgreSQL migration smoke.

- [ ] **Step 4: Run focused importer/ranking/deploy suites**

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
  app/tests/test_candidate_identity_backfill.py \
  app/tests/test_candidate_import_migration.py \
  app/tests/test_ranking.py -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend verification**

```bash
cd frontend-react
npm run lint
npx vitest run
npm run build
```

Expected: PASS.

- [ ] **Step 6: Review branch scope against the approved spec**

Run:

```bash
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Expected: importer, required ranking helper, migration/backfill/deployment infrastructure, tests, spec/plan, and targeted Candidates/Ranking integration only. No source-origin field, Browser Use, unrelated frontend redesign, or legacy bulk-endpoint removal.

- [ ] **Step 7: Push/open PR only after fresh green evidence**

PR title: `feat: add durable bulk candidate import pipeline`

PR body includes exact backend/frontend test results, migration `003`, new AWS resources, worker deployment/rollback notes, and `Closes #8`.
