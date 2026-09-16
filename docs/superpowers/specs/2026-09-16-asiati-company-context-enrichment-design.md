# ASIATI Company Context for Vacancy Enrichment

## Goal

Improve AI vacancy enrichment by providing stable organizational context about ASIATI separately from the vacancy draft and separately from the enrichment prompt implementation.

The enrichment model should understand the company's operating environment, business model and talent principles, while preserving recruiter control over hard requirements.

## Decision

Use a versioned `CompanyContext` resource (approach B).

The enrichment flow becomes:

```text
job draft
   +
company context
   ↓
AI enrichment
   ↓
structured proposal
   ↓
HR review
   ↓
apply to local form
   ↓
normal job save/versioning flow
```

`CompanyContext` is not candidate data and is not part of candidate evaluation evidence. It is an input only to vacancy enrichment unless a future design explicitly extends its use.

## Boundary

Create a company-context boundary under the jobs/organization domain rather than embedding ASIATI text directly in the prompt.

Conceptual interface:

```python
CompanyContext(
    organization_name="ASIATI Corp",
    version=1,
    business_summary=...,
    operating_context=[...],
    business_capabilities=[...],
    culture_principles=[...],
    talent_principles=[...],
    recruiter_guidance=[...],
)
```

The enrichment service receives the current active context through an injected provider/repository:

```python
context = get_active_company_context(owner_sub)
proposal = enrich_job_draft(draft, company_context=context)
```

The model adapter must not know where the context is stored.

## ASIATI Context v1

The initial context is derived from ASIATI's current public company and careers material.

### Organization

- ASIATI Corp.
- International-expansion ecosystem integrating strategy, origin control and operational execution.
- Business environment spans Asia and Latin America and combines global capabilities with local execution.

### Operating context

- International expansion and market-entry work.
- Supplier/product/origin validation and control.
- Logistics, documentation, customs and operational execution.
- Cost, margin, risk and growth control.
- Multicultural and cross-border collaboration.

### Business principles

- Business-minded decision making with financial and strategic impact.
- Structured execution rather than improvisation.
- Structured adaptability as markets change.
- Data, measurable results, optimization and scaling.
- Method, control and long-term vision.

### Talent principles

- Professional growth and continuous learning.
- Collaboration across locations, cultures and perspectives.
- Continuous improvement and innovation.
- Curiosity and proposing solutions.
- Contribution based on practical experience.

### Recruiter guidance

The context should help the model propose responsibilities, competencies, domain knowledge, relevant KPIs and likely technical requirements for the role.

It must NOT automatically convert company culture or generic corporate principles into hard candidate filters.

Examples:

- `data and results culture` may justify suggesting measurable KPIs or analytical competencies;
- it must not invent a mandatory number of years in a "data-driven company";
- `cross-border operations` may justify suggesting English or international logistics knowledge where the role logically requires it;
- it must not make a language mandatory unless supported by the role/draft or clearly returned as an assumption to validate.

## Source Material

Initial context is based on public ASIATI material available on 2026-09-16:

- https://www.asiaticorp.com/
- https://www.asiaticorp.com/quienes-somos
- https://www.asiaticorp.com/jobs

These sources describe ASIATI as a 360-degree international-expansion ecosystem integrating strategy, origin and operations; they also state business mindset, structured execution, structured adaptability, data/results culture, professional growth, multicultural teamwork and continuous innovation.

The application should not scrape these sites at runtime. They are provenance for the initial context only.

## Storage and Versioning

Company context is independent of source code prompt text.

For the first implementation, store it as a tenant-scoped persisted resource with an integer version and active flag. This avoids requiring a code deployment when the corporate context changes.

Suggested fields:

- `id UUID PK`
- `owner_sub TEXT NOT NULL`
- `organization_name TEXT NOT NULL`
- `version INTEGER NOT NULL`
- `status TEXT NOT NULL` (`ACTIVE`, `ARCHIVED`)
- `context JSON NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Constraints:

- unique `(owner_sub, version)`;
- at most one active context per owner;
- enrichment always reads the active context;
- context history is retained for traceability.

This is configuration data, not a secret.

## Context Shape

The persisted JSON shape is:

```json
{
  "business_summary": "...",
  "operating_context": [],
  "business_capabilities": [],
  "culture_principles": [],
  "talent_principles": [],
  "recruiter_guidance": []
}
```

Lists use concise statements. No credentials, candidate data or private employee information are allowed.

## Enrichment Prompt Rules

The prompt receives three clearly separated blocks:

1. `COMPANY_CONTEXT`
2. `JOB_DRAFT`
3. `OUTPUT_CONTRACT`

Prompt rules must state:

- use company context to improve relevance, not to invent facts;
- company principles are contextual signals, not automatic hard requirements;
- do not claim ASIATI uses a technology/certification/tool unless the job draft or company context explicitly says so;
- uncertain role-specific implications go into `assumptions_to_validate`;
- separate required vs preferred technologies and certifications;
- suggest KPIs/responsibilities only when reasonable for the role;
- do not use protected-class or unrelated personal attributes;
- return strict schema-valid JSON.

## API Behavior

`POST /api/jobs/enrich` remains the public enrichment endpoint.

The frontend does not send the company context. The backend resolves it from the authenticated tenant so the client cannot accidentally or maliciously substitute another organization's context.

If no active company context exists, enrichment still works using only the job draft and an empty context.

The response may include non-sensitive provenance metadata:

```json
{
  "company_context_version": 1,
  "proposal": { ... }
}
```

This makes enrichment behavior auditable without exposing internal prompt text.

## Editing Context

The first implementation needs the domain/repository and seed for ASIATI context v1. A dedicated HR/admin UI for editing company context is not required in this feature block.

The persisted boundary intentionally allows a later settings endpoint/UI to update and activate a new version without changing the enrichment service.

Until that UI exists, administrative seeding/update can use a controlled migration/seed operation. The enrichment prompt remains free of ASIATI-specific hardcoded text.

## Relationship to Job Evaluation Versioning

Changing `CompanyContext` alone does NOT increment existing jobs' `evaluation_version` and does NOT automatically reevaluate candidates.

Reason: company context is used to generate an enrichment proposal, but HR must review and save the resulting vacancy changes. Only the normal job update path can invalidate evaluations.

Therefore:

```text
company context changes
        ↓
future enrichment proposals change
        ↓
no candidate reevaluation yet

HR applies enriched job changes
        ↓
job evaluation signature changes
        ↓
evaluation_version++
        ↓
reevaluation task
```

## Safety and Quality Rules

- No candidate CV or evaluation history is sent into vacancy enrichment.
- Context cannot introduce protected-class criteria.
- Context cannot silently turn cultural preferences into exclusionary requirements.
- Hard requirements must be supported by the job draft or explicitly accepted by HR after review.
- Organization-specific uncertainty must be visible in `assumptions_to_validate`.
- The model never persists the vacancy directly.

## Testing

Backend tests must prove:

- enrichment receives the active tenant-scoped company context;
- another tenant's context cannot be used;
- absence of context falls back safely;
- the returned provenance contains the correct context version;
- model input separates company context from job draft;
- context does not mutate the job;
- changing company context does not change a job evaluation version;
- malformed context is rejected at the persistence boundary;
- ASIATI context v1 satisfies the strict schema;
- company context contains no candidate data.

Existing enrichment tests still prove malformed model output fails safely and that candidate data is never used.

## Migration

Because revision `008` is already allocated to job intelligence, create a subsequent additive migration for the company-context table rather than modifying the meaning of `008` after it has been validated.

Use the next available revision in the branch at implementation time.

## Non-Goals

This change does not:

- add RAG/Knowledge Base retrieval for company context;
- scrape ASIATI's website at runtime;
- auto-update context from the public site;
- add an HR settings UI in this feature block;
- automatically reevaluate candidates when company context changes;
- put ASIATI-specific prose directly into the Bedrock prompt implementation.

## Continuation

After company context is wired into Task 5, continue the already approved job-intelligence plan: reevaluation worker, enrichment endpoint, non-invasive Jobs UI, full verification, then return to the Gmail AWS gate.
