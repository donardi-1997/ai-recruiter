# ASIATI Company Context Vacancy Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let HR optionally enrich a vacancy draft before creation using Bedrock plus the active, tenant-scoped ASIATI company context, without persisting anything until the recruiter explicitly creates the vacancy.

**Architecture:** Add a versioned `CompanyContext` persistence boundary independent from prompts and jobs, seed ASIATI context v1, then have `POST /api/jobs/enrich` resolve the active context from the authenticated tenant. The React create-vacancy form exposes an optional `Enriquecer con IA` action that previews a proposal and only copies it into local form state after explicit approval; `POST /api/jobs` remains the sole creation action.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite tests, Pydantic v2, existing Bedrock runtime/model adapter, React/Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-16-asiati-company-context-enrichment-design.md`

## Global Constraints

- Do not hardcode ASIATI prose inside the Bedrock prompt implementation.
- Company context is tenant-scoped configuration, not candidate data and not a secret.
- The frontend never submits or selects a company context; backend resolves the active context from authenticated `owner_sub`.
- Company context can guide responsibilities, competencies, domain knowledge and KPIs, but cannot silently become exclusionary candidate requirements.
- Organization-specific uncertainty belongs in `assumptions_to_validate`.
- Enrichment is optional and never auto-runs.
- Enrichment never writes a job, increments `evaluation_version`, or evaluates candidates.
- `Aplicar propuesta` updates React form state only; `Crear vacante` remains the only persistence action for a new vacancy.
- If enrichment fails, all recruiter-entered form values remain unchanged.
- No RAG/Knowledge Base lookup and no runtime web scraping in this version.

---

## File Structure

### New files

- `app/migrations/versions/009_company_context.py` — additive company-context table and ASIATI v1 seed.
- `app/domains/jobs/company_context.py` — strict context schema plus active-context repository/service boundary.
- `app/domains/jobs/enrichment.py` — draft enrichment orchestration and Bedrock prompt composition.
- `app/tests/test_company_context.py` — persistence, tenant isolation, seed and version contracts.
- `app/tests/test_job_enrichment.py` — context-aware enrichment and failure-safety contracts.
- `frontend-react/src/__tests__/Jobs.intelligence.test.jsx` — creation-only optional enrichment UX.

### Modified files

- `app/models.py` — add `CompanyContext` ORM model.
- `app/domains/jobs/schemas.py` — enrichment request/proposal schemas and structured evaluation profile fields.
- `app/domains/jobs/router.py` — authenticated `POST /api/jobs/enrich`.
- `app/tests/test_postgres_migrations.py` — assert Alembic head `009` and `company_contexts` schema.
- `frontend-react/src/pages/Jobs.jsx` — enrichment state, action, proposal preview and local apply flow.
- `frontend-react/src/pages/Jobs.css` — compact non-blocking enrichment controls and review panel.

---

### Task 1: Persist and seed versioned tenant company context

**Files:**
- Modify: `app/models.py`
- Create: `app/migrations/versions/009_company_context.py`
- Create: `app/domains/jobs/company_context.py`
- Create: `app/tests/test_company_context.py`
- Modify: `app/tests/test_postgres_migrations.py`

**Interfaces:**
- Produces ORM model `CompanyContext`.
- Produces `CompanyContextPayload` Pydantic schema.
- Produces `get_active_company_context(db, *, owner_sub: str) -> CompanyContext | None`.
- Produces `validated_context_payload(row) -> CompanyContextPayload`.

- [ ] **Step 1: Write failing persistence and tenant-isolation tests**

Create tests proving the expected model/repository contract:

```python
def test_active_company_context_is_tenant_scoped(db):
    own = CompanyContext(owner_sub="owner-1", organization_name="ASIATI Corp", version=1, status="ACTIVE", context=VALID_CONTEXT)
    other = CompanyContext(owner_sub="owner-2", organization_name="Other", version=1, status="ACTIVE", context=VALID_CONTEXT)
    db.add_all([own, other])
    db.commit()

    result = get_active_company_context(db, owner_sub="owner-1")
    assert result.id == own.id
    assert result.owner_sub == "owner-1"
```

Also prove:
- unique `(owner_sub, version)`;
- invalid/malformed context is rejected by the schema boundary;
- ASIATI v1 context validates;
- the context JSON contains no candidate fields such as `candidate_id`, `resume`, `email`, or `evaluation`.

- [ ] **Step 2: Run targeted tests and confirm RED**

```bash
python -m pytest app/tests/test_company_context.py app/tests/test_postgres_migrations.py -v --tb=short
```

Expected: missing `CompanyContext`, migration `009`, and context service.

- [ ] **Step 3: Add strict context schema and repository boundary**

Implement:

```python
class CompanyContextPayload(BaseModel):
    business_summary: str
    operating_context: list[str] = Field(default_factory=list)
    business_capabilities: list[str] = Field(default_factory=list)
    culture_principles: list[str] = Field(default_factory=list)
    talent_principles: list[str] = Field(default_factory=list)
    recruiter_guidance: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
```

`get_active_company_context` must filter both `owner_sub` and `status == "ACTIVE"`, order newest version first, and return at most one row.

- [ ] **Step 4: Add ORM model and Alembic 009**

Model fields:

```python
id: UUID PK
owner_sub: TEXT NOT NULL
organization_name: TEXT NOT NULL
version: INTEGER NOT NULL
status: TEXT NOT NULL
context: JSON NOT NULL
created_at: TIMESTAMPTZ NOT NULL
updated_at: TIMESTAMPTZ NOT NULL
```

Constraints/indexes:

```python
UniqueConstraint("owner_sub", "version", name="uq_company_context_owner_version")
Index("idx_company_context_owner_status", "owner_sub", "status")
```

Revision metadata:

```python
revision = "009"
down_revision = "008"
```

The migration seeds ASIATI v1 only for a controlled configured/default tenant seed strategy already used by this repository; if no safe owner identifier is available at migration time, create the table only and expose an idempotent `ensure_asiati_context_v1(db, owner_sub=...)` seed helper for application/admin invocation rather than inventing an owner ID.

- [ ] **Step 5: Extend PostgreSQL smoke and confirm GREEN**

Assert:

```python
assert "company_contexts" in inspector.get_table_names()
assert revision == "009"
```

Then run the targeted tests again and let CI PostgreSQL smoke validate the migration.

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/migrations/versions/009_company_context.py app/domains/jobs/company_context.py app/tests/test_company_context.py app/tests/test_postgres_migrations.py
git commit -m "feat: add versioned tenant company context"
```

---

### Task 2: Context-aware vacancy enrichment API

**Files:**
- Create: `app/domains/jobs/enrichment.py`
- Modify: `app/domains/jobs/schemas.py`
- Modify: `app/domains/jobs/router.py`
- Create: `app/tests/test_job_enrichment.py`

**Interfaces:**
- Consumes `get_active_company_context(db, *, owner_sub)`.
- Produces `JobEnrichmentRequest`.
- Produces `JobEnrichmentProposal`.
- Produces `enrich_job_draft(db, *, owner_sub: str, request: JobEnrichmentRequest, model_client=None) -> tuple[JobEnrichmentProposal, int | None]`.
- Exposes `POST /api/jobs/enrich`.

- [ ] **Step 1: Write failing enrichment tests**

Cover:

```python
def test_enrichment_uses_active_tenant_context(...): ...
def test_enrichment_never_reads_other_tenant_context(...): ...
def test_enrichment_works_without_active_context(...): ...
def test_enrichment_returns_context_version_provenance(...): ...
def test_enrichment_model_input_separates_company_context_and_job_draft(...): ...
def test_enrichment_does_not_write_job_or_change_evaluation_version(...): ...
def test_malformed_model_output_fails_without_mutation(...): ...
def test_enrichment_never_uses_candidate_data(...): ...
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
python -m pytest app/tests/test_job_enrichment.py -v --tb=short
```

- [ ] **Step 3: Define strict request/proposal schemas**

`JobEnrichmentRequest` accepts draft fields only:

```python
title: str
description: str | None = None
country_code: str | None = None
city: str | None = None
employment_type: str | None = None
evaluation_profile: EvaluationProfile | None = None
```

`JobEnrichmentProposal` includes:

```python
improved_description: str
required_technologies: list[str]
preferred_technologies: list[str]
required_certifications: list[str]
preferred_certifications: list[str]
minimum_years_experience: int | None
specific_experience: list[str]
responsibilities: list[str]
domain_knowledge: list[str]
education: list[str]
languages: list[str]
technical_competencies: list[str]
assumptions_to_validate: list[str]
```

Use `Field(default_factory=list)` and forbid unexpected model output.

- [ ] **Step 4: Build prompt from three explicit blocks**

The model input must be structurally separated as:

```text
COMPANY_CONTEXT
<validated tenant context or empty context>

JOB_DRAFT
<current unsaved recruiter fields>

OUTPUT_CONTRACT
<strict JSON field contract>
```

Prompt instructions must explicitly state:

```text
Use company context only to improve relevance.
Do not invent company-specific tools, technologies or certifications.
Company principles are context, not automatic hard candidate requirements.
Put uncertain role-specific implications in assumptions_to_validate.
Separate required from preferred technologies and certifications.
Do not use protected-class or unrelated personal attributes.
Return JSON only.
```

Reuse the repository's existing Bedrock runtime/model configuration and inject the model call in tests.

- [ ] **Step 5: Validate output before returning**

Parse the model JSON through `JobEnrichmentProposal`. Invalid JSON/schema raises a typed domain exception; router maps it to a controlled 502/503 response and no persistence is performed.

- [ ] **Step 6: Add authenticated endpoint**

`POST /api/jobs/enrich` receives the draft, takes `owner_sub` only from `get_current_user`, calls the service, and returns:

```json
{
  "company_context_version": 1,
  "proposal": { "improved_description": "..." }
}
```

No `job_id` is required because this flow runs before creation.

- [ ] **Step 7: Run targeted + domain regressions and commit**

```bash
python -m pytest app/tests/test_company_context.py app/tests/test_job_enrichment.py app/tests/test_jobs_domain.py -v --tb=short
```

```bash
git add app/domains/jobs app/tests/test_job_enrichment.py
git commit -m "feat: enrich vacancy drafts with company context"
```

---

### Task 3: Optional enrichment inside create-vacancy UI

**Files:**
- Modify: `frontend-react/src/pages/Jobs.jsx`
- Modify: `frontend-react/src/pages/Jobs.css`
- Create: `frontend-react/src/__tests__/Jobs.intelligence.test.jsx`

**Interfaces:**
- Calls `POST /jobs/enrich` only from the create-vacancy form (`editingJob == null`).
- `Aplicar propuesta` mutates local form state only.
- Existing `saveJob` remains the only job persistence path.

- [ ] **Step 1: Write RED frontend tests**

Prove:

```text
- Nueva vacante shows "Enriquecer con IA".
- Editar vacante does not show the creation-only enrichment button in this version.
- Clicking enrichment sends current title/description/location/employment data.
- The button becomes "Enriqueciendo…" but the rest of the form stays editable.
- Proposal renders before application.
- "Aplicar propuesta" changes local form fields/profile only and performs no POST /jobs.
- "Descartar" leaves recruiter draft unchanged.
- Enrichment error leaves recruiter draft unchanged.
- "Crear vacante" is still the only action that POSTs /jobs.
```

- [ ] **Step 2: Run the new Vitest file and confirm RED**

```bash
cd frontend-react
npx vitest run src/__tests__/Jobs.intelligence.test.jsx
```

- [ ] **Step 3: Add isolated enrichment UI state**

Add state separate from `saving`:

```javascript
const [enriching, setEnriching] = useState(false);
const [enrichmentProposal, setEnrichmentProposal] = useState(null);
const [enrichmentError, setEnrichmentError] = useState("");
```

Reset those values when starting/cancelling a create form.

- [ ] **Step 4: Add optional creation-only button**

Render beneath title/description when `!editingJob`:

```jsx
<button type="button" onClick={enrichJobDraft} disabled={enriching || !title.trim()}>
  {enriching ? "Enriqueciendo…" : "Enriquecer con IA"}
</button>
```

The request uses current local draft values and never triggers `saveJob`.

- [ ] **Step 5: Add proposal review panel**

Render improved description, required/preferred technologies, certifications, experience, responsibilities and assumptions. Buttons:

```text
Descartar
Aplicar propuesta
```

`Aplicar propuesta` copies `proposal.improved_description` into `description` and stores the structured proposal as `evaluationProfile` local state. It does not call the API.

- [ ] **Step 6: Include profile only when the recruiter creates the vacancy**

Extend the normal creation payload with:

```javascript
evaluation_profile: evaluationProfile
```

The existing `POST /jobs` remains the persistence boundary.

- [ ] **Step 7: Run frontend regressions**

```bash
cd frontend-react
npx vitest run
npm run lint
npm run build
```

- [ ] **Step 8: Commit**

```bash
git add frontend-react/src/pages/Jobs.jsx frontend-react/src/pages/Jobs.css frontend-react/src/__tests__/Jobs.intelligence.test.jsx
git commit -m "feat: add optional ai enrichment before vacancy creation"
```

---

### Task 4: Full verification and continuation gate

**Files:** no new feature files; verification only.

- [ ] **Step 1: Run full backend test suite**

```bash
python -m pytest app/tests/ -v --tb=short
```

- [ ] **Step 2: Run PostgreSQL/Alembic smoke**

Confirm migration head `009` and `company_contexts` schema in CI.

- [ ] **Step 3: Run full frontend verification**

```bash
cd frontend-react
npx vitest run
npm run lint
npm run build
```

- [ ] **Step 4: Confirm no unintended AWS provisioning**

This feature block must not create or modify AWS infrastructure. After all checks are green, return to the previously approved Gmail AWS gate: Google OAuth for the personal Gmail account, Secrets Manager in `us-east-2`, then a real-mail end-to-end ingestion test.
