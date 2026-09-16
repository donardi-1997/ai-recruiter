# Job Intelligence and Versioned Evaluations Design

## Goal

Make job definitions safely editable and AI-assisted while ensuring candidate evaluations are reused when the job evaluation profile has not changed and are recomputed only when evaluation-relevant job content changes.

## Scope

This design covers three connected capabilities:

1. Editable vacancies with a discreet warning that evaluation-relevant changes will trigger reevaluation of assigned candidates.
2. Version-aware evaluation reuse so a candidate is not reevaluated against an unchanged vacancy.
3. AI-assisted vacancy enrichment that proposes technical requirements, certifications, domain experience, responsibilities, education, languages, and assumptions for HR review before applying changes.

It does not change the Gmail ingestion design, Indeed ingestion design, tenant ownership model, Bedrock knowledge-base storage model, or ranking semantics except where reevaluation must regenerate ranking data.

## Current State

Jobs are already editable through `PUT /api/jobs/{job_id}`. Evaluations are persisted by candidate/job pair, but the evaluation service currently runs retrieval and LLM evaluation whenever called. A repository helper can identify complete evaluations, but no durable representation exists for the exact job profile version used to produce an evaluation.

## Core Design Decision

Use an explicit integer `evaluation_version` on each job and store `job_evaluation_version` on each evaluation.

An evaluation is current only when all of the following are true:

- it belongs to the same candidate and job;
- its status is `COMPLETED`;
- it passes the existing completeness rules;
- `evaluation.job_evaluation_version == job.evaluation_version`.

If these conditions hold, evaluation callers must return the persisted evaluation without invoking retrieval or the LLM.

If the job version differs, the evaluation is stale and must be recomputed.

## Job Model Changes

Add the following fields to `jobs`:

- `evaluation_version INTEGER NOT NULL DEFAULT 1`
- `evaluation_profile JSON NOT NULL DEFAULT {}`
- `updated_at TIMESTAMPTZ NOT NULL`

`evaluation_profile` is structured data used by the evaluator. Initial keys are:

```json
{
  "required_technologies": [],
  "preferred_technologies": [],
  "required_certifications": [],
  "preferred_certifications": [],
  "minimum_years_experience": null,
  "specific_experience": [],
  "responsibilities": [],
  "domain_knowledge": [],
  "education": [],
  "languages": [],
  "technical_competencies": [],
  "assumptions_to_validate": []
}
```

Empty profiles are valid for existing jobs and preserve current title/description-driven evaluation behavior.

## Evaluation Model Changes

Add to `evaluations`:

- `job_evaluation_version INTEGER NOT NULL DEFAULT 1`

When an evaluation is created or updated, it must store the current `job.evaluation_version`.

Existing evaluations are migrated to version `1`, matching existing jobs migrated to version `1`.

## Evaluation-Relevant Changes

The following changes increment `job.evaluation_version`:

- `title`
- `description`
- `evaluation_profile`

The following publication-only changes do not increment the evaluation version:

- `public_slug`
- `published_at`

`country_code`, `city`, and `employment_type` are treated as publication/operational metadata unless the HR user explicitly applies them into `evaluation_profile`. Therefore changing them alone does not invalidate evaluations.

Before persisting an update, the service compares normalized old and new evaluation-relevant content. Saving identical values must not increment the version or enqueue reevaluation.

## Evaluation Reuse Rule

The central evaluation service owns freshness checks. Callers must not implement their own version comparison.

The evaluation flow becomes:

```text
candidate + job
      ↓
load persisted evaluation
      ↓
complete and same job version?
   ↙ yes              ↘ no
return existing      retrieve candidate
0 LLM calls               ↓
                      evaluate with LLM
                           ↓
                   persist current version
```

The returned `newly_evaluated` flag is `False` when an existing current evaluation is reused and `True` when the LLM actually runs or a failed/stale evaluation is replaced.

A `force=True` internal option may bypass the freshness check for explicit administrative/debugging cases, but normal UI and ingestion flows must not use it.

## Reevaluation After Job Updates

Evaluation-relevant job updates must not synchronously evaluate every candidate inside the HTTP request.

Add a durable reevaluation task model:

### `job_reevaluation_tasks`

Fields:

- `id UUID PK`
- `owner_sub TEXT NOT NULL`
- `job_id UUID NOT NULL`
- `target_evaluation_version INTEGER NOT NULL`
- `status TEXT NOT NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `queue_dispatched_at TIMESTAMPTZ NULL`
- `processing_token TEXT NULL`
- `heartbeat_at TIMESTAMPTZ NULL`
- `last_error_code TEXT NULL`
- `last_error_message TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `completed_at TIMESTAMPTZ NULL`

Create a unique constraint on `(job_id, target_evaluation_version)` so repeated saves/retries cannot create duplicate work for the same job version.

The shared SQS worker receives a new work kind such as `job_reevaluation`. The handler:

1. loads the task tenant-safely;
2. verifies the job still exists and its current version is at least the target version;
3. loads assigned candidates for the job;
4. calls the central evaluation service for each candidate;
5. skips candidates whose evaluation is already current for the target/current job version;
6. rebuilds the job ranking after candidate evaluation processing;
7. marks the task completed.

If the job changes again while an older task is queued, the older task must not overwrite newer evaluations. The central freshness rule always compares against the current job version; therefore candidates may be evaluated directly against the newest version, and subsequent stale work becomes a no-op where possible.

## UI Behavior for Editing Jobs

The existing job edit form remains the primary interface.

When editing a job with one or more assigned/evaluated candidates, show a small inline informational notice near the save action:

> Esta vacante tiene candidatos evaluados. Los cambios en el perfil harán que sus evaluaciones se actualicen automáticamente.

This is informational only. Do not use a blocking modal or require a confirmation checkbox.

After a version-changing save, show a transient success status such as:

> Perfil actualizado · reevaluación de 18 candidatos pendiente

If the save changes only publication metadata or submits identical evaluation content, show the normal save confirmation without mentioning reevaluation.

The backend response should explicitly tell the frontend whether evaluation content changed and how many assigned candidates are affected. Proposed response metadata:

```json
{
  "job_id": "...",
  "evaluation_version": 4,
  "evaluation_changed": true,
  "reevaluation_scheduled": true,
  "reevaluation_candidate_count": 18
}
```

## AI Vacancy Enrichment

Add an explicit user action in the job form:

> Enriquecer con IA

Enrichment is advisory. It must not directly persist changes or increment `evaluation_version`.

### Input

The enrichment service receives the current editable job draft:

- title
- description
- country/city/employment type when present as context
- current evaluation profile when present

### Output

The service returns a structured proposal with:

- improved description
- required technologies
- preferred technologies
- required certifications
- preferred certifications
- minimum years of experience
- specific experience
- responsibilities
- domain knowledge
- education
- languages
- technical competencies
- assumptions/questions that HR should validate

The model must distinguish mandatory requirements from suggestions. It must not silently convert a suggested certification or technology into a hard requirement.

### Review Before Apply

The frontend presents the enrichment proposal before applying it. HR may accept the complete proposal or edit individual fields in the normal job form/profile editor.

Only when HR applies/saves the enriched profile does the ordinary job update logic run. If evaluation-relevant content differs, `evaluation_version` increments exactly once and reevaluation is scheduled.

## Enrichment Prompt Rules

The prompt should instruct the model to:

- infer common requirements for the role from title and description;
- avoid asserting organization-specific technologies unless supported by the job text;
- place uncertain organization-specific assumptions into `assumptions_to_validate`;
- separate required and preferred technologies/certifications;
- avoid protected-class criteria or unrelated personal attributes;
- return strict structured JSON compatible with a validated Pydantic schema;
- use concise, recruiter-readable language.

The enrichment endpoint is tenant-authenticated but does not require candidate data.

## API Additions and Changes

### Update Job

`PUT /api/jobs/{job_id}` remains the update endpoint. Its request gains optional `evaluation_profile`.

Its response gains:

- `evaluation_version`
- `evaluation_profile`
- `evaluation_changed`
- `reevaluation_scheduled`
- `reevaluation_candidate_count`

### Enrich Draft

Add:

`POST /api/jobs/enrich`

The endpoint accepts a job draft rather than a persisted job ID so HR can enrich both new and existing jobs before saving.

It returns the structured enrichment proposal and does not mutate the database.

## Failure Handling

### Evaluation Reuse

If a current completed evaluation exists, downstream Bedrock/network failures are irrelevant because no external evaluation call occurs.

### Reevaluation Worker

Transient worker failures use the existing shared queue retry/DLQ conventions. Task checkpoints and attempt counters make processing observable and retryable.

A single candidate evaluation failure should not erase prior successful candidate evaluations. The task records failure details and follows the existing evaluation failure semantics.

### Enrichment

If the enrichment LLM response is malformed, invalid, or unavailable, return a controlled API error and leave the job draft unchanged. No `evaluation_version` changes occur.

## Tenant Isolation

All job, candidate, reevaluation task, and enrichment operations are scoped by the authenticated `owner_sub` where persisted resources are involved.

A user cannot trigger reevaluation for another tenant's job or inspect its candidate counts/profile.

## Migration

Create Alembic revision `008` after existing revision `007`.

The migration will:

1. add `jobs.evaluation_version` with default `1`;
2. add `jobs.evaluation_profile` with empty JSON default/backfill;
3. add `jobs.updated_at` and backfill existing rows;
4. add `evaluations.job_evaluation_version` with default/backfill `1`;
5. create `job_reevaluation_tasks` and its indexes/unique constraint;
6. remove temporary server defaults where appropriate while retaining ORM defaults.

PostgreSQL smoke coverage must assert the new columns, table, and Alembic head `008`.

## Testing Strategy

Backend tests must prove:

- an existing complete evaluation for the current job version returns without calling retrieval or LLM;
- a stale evaluation triggers a new LLM evaluation;
- a failed/incomplete evaluation is retried even when its stored version matches;
- `force=True` triggers reevaluation;
- title, description, and evaluation-profile changes increment `evaluation_version`;
- identical content does not increment the version;
- publication-only changes do not increment the version;
- one durable reevaluation task is created per job/version;
- retries do not create duplicate tasks;
- reevaluation skips already-current candidates;
- tenant isolation is maintained;
- enrichment returns schema-valid structured output;
- enrichment does not persist or increment versions;
- malformed enrichment output fails safely;
- migration `008` succeeds on PostgreSQL.

Frontend tests must prove:

- the inline reevaluation notice appears when editing a job with affected candidates;
- the notice is non-blocking;
- enrichment can be requested from the form;
- the proposal is displayed before application;
- applying a proposal updates editable fields but does not save until the user submits;
- version-changing save displays the pending reevaluation message;
- metadata-only save does not claim reevaluation was scheduled.

## Non-Goals

This change does not:

- automatically rewrite vacancies without HR review;
- use candidate data to enrich a vacancy;
- create a full immutable job revision history;
- introduce a second queue;
- modify Indeed approval/onboarding behavior;
- change Gmail OAuth or mailbox synchronization;
- deploy new AWS infrastructure during this feature block.

## Continuation Point

After this feature is implemented and CI is green, resume the Gmail integration at the previously identified AWS gate: Google OAuth for the personal Gmail account, secret storage in AWS Secrets Manager in `us-east-2`, and an end-to-end real-mail ingestion test.