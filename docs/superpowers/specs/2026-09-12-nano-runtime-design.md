# Nano Runtime Optimization Design

## Goal

Run AI Recruiter reliably on a 512 MiB Lightsail Nano for one occasional user without removing any existing product capability.

## Non-negotiable behavior

- Keep PDF, DOCX and ZIP imports.
- Keep the 500-CV batch limit.
- Keep 15 MiB per direct document and 500 MiB per ZIP upload limits.
- Keep the 1 GiB expanded-batch safety budget.
- Keep automatic Bedrock ingestion, candidate evaluation and ranking.
- Keep durable SQS worker semantics, idempotency, tenant isolation and retry behavior.
- Keep one Uvicorn process and the existing Nginx frontend model.
- Production Nano profile uses one concurrent candidate evaluation.

## Architecture

### 1. Memory-bounded ZIP processing

The current implementation reads the complete ZIP into memory and then materializes all expanded children as `bytes` in a list. The Nano design replaces that with a temporary-file/streaming boundary:

1. S3 staging object is downloaded in chunks into a `tempfile.SpooledTemporaryFile` or named temporary file rather than returned as one `bytes` object.
2. ZIP metadata is validated before child extraction. Path traversal, symlinks, encrypted entries, nested archives, per-document size, document-count limit and expanded-byte budget remain enforced.
3. Supported children are yielded one at a time as `ExpandedDocument` payloads.
4. The worker writes each child to staging S3 and immediately releases its bytes before moving to the next child.
5. Worker retry checkpoints stay unchanged: once an archive is fully expanded successfully, its persisted children are the resume boundary.

Peak archive-processing memory therefore scales with one child document plus parser overhead, not with the compressed archive plus every expanded child.

### 2. Lazy heavy imports

`fitz` and `python-docx` are imported inside the PDF/DOCX extraction functions instead of at module import time. API startup can include candidate-import routes without eagerly loading PDF/DOCX native libraries. Worker behavior and parsing contracts remain unchanged.

### 3. Low-memory database/runtime profile

Application defaults remain safe for existing environments, but deployment explicitly sets a Nano profile:

- `IMPORT_EVALUATION_CONCURRENCY=1`
- `PG_POOL_SIZE=2`
- `PG_MAX_OVERFLOW=2`

The worker remains resident because SQS durability depends on it. Bedrock inference and Knowledge Base work remain remote.

### 4. Nano host profile

Add an idempotent host configuration script that prepares a small Lightsail instance with:

- 2 GiB swap file if equivalent swap is not already configured.
- conservative `vm.swappiness` suitable as an OOM safety net rather than primary memory.
- Docker json-file log rotation.
- PostgreSQL low-memory settings appropriate for a single-user workload.
- no destructive database recreation.

The script must be safe to rerun and must print the resulting memory/swap/PostgreSQL/Docker configuration for verification.

### 5. Deployment hygiene

Production deploy scripts pass the Nano runtime settings to API/worker, preserve the current rollback image, and prune unused old Docker images only after health verification. The frontend remains a small Nginx container. No application image is built on the Nano host; GitHub Actions/ECR continues doing builds remotely.

## Error handling and durability

Archive validation remains fail-closed. A malformed, encrypted, unsafe or over-budget archive fails deterministically with the existing public-safe error contracts. Temporary files are always closed/deleted with context managers/finally semantics. A failed archive expansion does not mark the archive completed. Existing SQS retry/DLQ behavior remains unchanged.

## Testing

- Unit tests prove ZIP children are consumed incrementally and archive safety rules remain intact.
- Worker tests prove each yielded child is staged independently and the archive is checkpointed only after complete iteration.
- Configuration tests prove Nano environment values are honored without changing application defaults.
- Deployment tests assert Nano concurrency/pool variables, swap/log-rotation host script behavior and post-success image pruning.
- Full backend, frontend, contract and PostgreSQL CI must remain green.

## Acceptance criteria

1. No code path materializes a 500 MiB ZIP plus all expanded children in Python memory.
2. Existing import limits and safety semantics are preserved.
3. Candidate evaluation concurrency can be set to 1 in production and deploy does so.
4. SQLAlchemy pool can be constrained to 2 + 2 via environment variables and deploy does so.
5. A repeatable Nano host-tuning script exists with 2 GiB swap and Docker/PostgreSQL low-memory settings.
6. Deploy cleans stale Docker images only after successful runtime verification.
7. All existing tests plus new Nano-runtime tests pass.