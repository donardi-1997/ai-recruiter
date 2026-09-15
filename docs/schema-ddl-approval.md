# Esquema Relacional — AI Recruiter (PostgreSQL)

> **Estado:** Para aprobación
> **Fecha:** 2026-09-05
> **Nota:** Partimos desde cero. No se migran datos antiguos.

---

## Variables a sustituir

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `DATABASE_URL` | URL de conexión a PostgreSQL | `postgresql://user:pass@host:5432/ai_recruiter` |
| `REEMPLAZAR_DB_TABLE_CANDIDATES` | Nombre de tabla candidates | `ai_recruiter_candidates` |
| `REEMPLAZAR_DB_TABLE_JOBS` | Nombre de tabla jobs | `ai_recruiter_jobs` |
| `REEMPLAZAR_DB_TABLE_EVALUATIONS` | Nombre de tabla evaluations | `ai_recruiter_evaluations` |
| `REEMPLAZAR_DB_TABLE_JOB_CANDIDATES` | Nombre de tabla pivote | `ai_recruiter_job_candidates` |
| `REEMPLAZAR_DB_TABLE_RANKINGS` | Nombre de tabla rankings metadata | `ai_recruiter_rankings` |
| `REEMPLAZAR_DB_TABLE_RANKING_ITEMS` | Nombre de tabla ranking items | `ai_recruiter_ranking_items` |

---

## DDL SQL

```sql
-- ============================================================
-- 1. CANDIDATES
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_CANDIDATES (
    candidate_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id            TEXT NOT NULL,
    name                TEXT NOT NULL,
    filename            TEXT NOT NULL,
    s3_location         TEXT NOT NULL,
    metadata_location   TEXT,
    ingestion_job_id    TEXT,
    ingestion_status    TEXT,
    indexed             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_CANDIDATES IS 'Candidatos subidos por usuarios. Un candidato = un CV en S3.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_CANDIDATES.candidate_id IS 'UUID v4 generado por la aplicación.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_CANDIDATES.owner_id IS 'Cognito sub del propietario.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_CANDIDATES.s3_location IS 'URI completa: s3://bucket/prefix/cv-{id}.pdf';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_CANDIDATES.indexed IS 'TRUE cuando Bedrock terminó de indexar el CV.';

CREATE INDEX idx_candidates_owner
    ON REEMPLAZAR_DB_TABLE_CANDIDATES (owner_id);

-- ============================================================
-- 2. JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_JOBS (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_JOBS IS 'Vacantes de empleo. La description se usa como prompt de Bedrock para evaluar candidatos.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_JOBS.description IS 'Descripción completa de la vacante. Puede ser largo (hasta 10KB).';

CREATE INDEX idx_jobs_owner
    ON REEMPLAZAR_DB_TABLE_JOBS (owner_id);

-- ============================================================
-- 3. JOB ↔ CANDIDATE (tabla pivote)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_JOB_CANDIDATES (
    job_id          UUID NOT NULL REFERENCES REEMPLAZAR_DB_TABLE_JOBS(job_id) ON DELETE CASCADE,
    candidate_id    UUID NOT NULL REFERENCES REEMPLAZAR_DB_TABLE_CANDIDATES(candidate_id) ON DELETE CASCADE,
    owner_id        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING_EVALUATION',
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, candidate_id)
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_JOB_CANDIDATES IS 'Asignación de candidatos a vacantes. Tabla pivote N:M.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_JOB_CANDIDATES.status IS 'PENDING_EVALUATION | EVALUATED';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_JOB_CANDIDATES.assigned_at IS 'Usado para modo incremental: candidatos nuevos desde último ranking.';

CREATE INDEX idx_job_candidates_candidate
    ON REEMPLAZAR_DB_TABLE_JOB_CANDIDATES (candidate_id);

CREATE INDEX idx_job_candidates_owner
    ON REEMPLAZAR_DB_TABLE_JOB_CANDIDATES (owner_id);

-- ============================================================
-- 4. EVALUATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_EVALUATIONS (
    job_id              UUID NOT NULL REFERENCES REEMPLAZAR_DB_TABLE_JOBS(job_id) ON DELETE CASCADE,
    candidate_id        UUID NOT NULL REFERENCES REEMPLAZAR_DB_TABLE_CANDIDATES(candidate_id) ON DELETE CASCADE,
    owner_id            TEXT NOT NULL,
    job_title           TEXT NOT NULL DEFAULT '',
    job_description     TEXT NOT NULL DEFAULT '',
    candidate_name      TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'PENDING',
    evaluated_at        TIMESTAMPTZ,
    match_score         INTEGER NOT NULL DEFAULT 0,
    recommendation      TEXT NOT NULL DEFAULT 'LOW_MATCH',
    requirements        JSONB NOT NULL DEFAULT '[]'::JSONB,
    strengths           JSONB NOT NULL DEFAULT '[]'::JSONB,
    gaps                JSONB NOT NULL DEFAULT '[]'::JSONB,
    summary             TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job_id, candidate_id)
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_EVALUATIONS IS 'Resultado de evaluar un candidato contra una vacante usando Bedrock.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_EVALUATIONS.match_score IS 'Puntaje 0-100. Generado por el LLM.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_EVALUATIONS.recommendation IS 'STRONG_MATCH | GOOD_MATCH | PARTIAL_MATCH | LOW_MATCH';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_EVALUATIONS.requirements IS 'JSONB: [{requirement, status, evidence}]';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_EVALUATIONS.strengths IS 'JSONB: ["fortaleza 1", "fortaleza 2"]';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_EVALUATIONS.gaps IS 'JSONB: ["brecha 1", "brecha 2"]';

CREATE INDEX idx_evaluations_candidate
    ON REEMPLAZAR_DB_TABLE_EVALUATIONS (candidate_id);

CREATE INDEX idx_evaluations_owner
    ON REEMPLAZAR_DB_TABLE_EVALUATIONS (owner_id);

CREATE INDEX idx_evaluations_score
    ON REEMPLAZAR_DB_TABLE_EVALUATIONS (match_score DESC);

CREATE INDEX idx_evaluations_recommendation
    ON REEMPLAZAR_DB_TABLE_EVALUATIONS (recommendation);

-- Índice principal del ranking: cubre ORDER BY match_score DESC por job
CREATE INDEX idx_evaluations_job_score
    ON REEMPLAZAR_DB_TABLE_EVALUATIONS (job_id, match_score DESC);

-- ============================================================
-- 5. RANKINGS (metadata del último ranking por job)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_RANKINGS (
    job_id                  UUID PRIMARY KEY REFERENCES REEMPLAZAR_DB_TABLE_JOBS(job_id) ON DELETE CASCADE,
    ranking_generated_at    TIMESTAMPTZ,
    ranking_version         INTEGER NOT NULL DEFAULT 0
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_RANKINGS IS 'Metadata del último ranking ejecutado por cada vacante. 1:1 con jobs.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_RANKINGS.ranking_version IS 'Versión incremental. Se incrementa en cada recalculate.';

-- ============================================================
-- 6. RANKING ITEMS (snapshot de cada ejecución de ranking)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_DB_TABLE_RANKING_ITEMS (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id          UUID NOT NULL REFERENCES REEMPLAZAR_DB_TABLE_JOBS(job_id) ON DELETE CASCADE,
    candidate_id    UUID NOT NULL,
    candidate_name  TEXT NOT NULL DEFAULT '',
    match_score     REAL NOT NULL DEFAULT 0.0,
    recommendation  TEXT NOT NULL DEFAULT 'LOW_MATCH',
    status          TEXT NOT NULL DEFAULT 'COMPLETED',
    rank_position   INTEGER NOT NULL,
    strengths       JSONB NOT NULL DEFAULT '[]'::JSONB,
    gaps            JSONB NOT NULL DEFAULT '[]'::JSONB,
    ranking_version INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE REEMPLAZAR_DB_TABLE_RANKING_ITEMS IS 'Snapshot de cada ejecución de ranking. Permite ver evolución histórica.';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_RANKING_ITEMS.rank_position IS 'Posición en el ranking (1 = mejor).';
COMMENT ON COLUMN REEMPLAZAR_DB_TABLE_RANKING_ITEMS.ranking_version IS 'Versión del ranking al que pertenece este snapshot.';

CREATE INDEX idx_ranking_items_job
    ON REEMPLAZAR_DB_TABLE_RANKING_ITEMS (job_id);

CREATE UNIQUE INDEX uq_ranking_item_per_version
    ON REEMPLAZAR_DB_TABLE_RANKING_ITEMS (job_id, ranking_version, candidate_id);
```

---

## Resumen de índices

| # | Tabla | Índice | Columnas | Propósito |
|---|-------|--------|----------|-----------|
| 1 | candidates | `idx_candidates_owner` | `owner_id` | Listar candidatos de un usuario |
| 2 | jobs | `idx_jobs_owner` | `owner_id` | Listar vacantes de un usuario |
| 3 | job_candidates | `idx_job_candidates_candidate` | `candidate_id` | Búsqueda inversa: ¿en qué vacantes? |
| 4 | job_candidates | `idx_job_candidates_owner` | `owner_id` | Scope `all` |
| 5 | evaluations | `idx_evaluations_candidate` | `candidate_id` | Historial por candidato |
| 6 | evaluations | `idx_evaluations_owner` | `owner_id` | Scope `all` |
| 7 | evaluations | `idx_evaluations_score` | `match_score DESC` | Ranking global |
| 8 | evaluations | `idx_evaluations_recommendation` | `recommendation` | Filtro por clasificación |
| 9 | evaluations | `idx_evaluations_job_score` | `(job_id, match_score DESC)` | **Índice principal del ranking** |
| 10 | ranking_items | `idx_ranking_items_job` | `job_id` | Recuperar items por job |
| 11 | ranking_items | `uq_ranking_item_per_version` | `(job_id, ranking_version, candidate_id)` | Integridad + lookup |

---

## Constraints y FKs

| Constraint | Tabla | Tipo | Columnas | Acción |
|------------|-------|------|----------|--------|
| `candidates_pkey` | candidates | PK | `candidate_id` | — |
| `jobs_pkey` | jobs | PK | `job_id` | — |
| `job_candidates_pkey` | job_candidates | PK | `(job_id, candidate_id)` | — |
| `evaluations_pkey` | evaluations | PK | `(job_id, candidate_id)` | — |
| `rankings_pkey` | rankings | PK | `job_id` | — |
| `ranking_items_pkey` | ranking_items | PK | `id` | — |
| FK job_candidates → jobs | job_candidates | FK | `job_id` | CASCADE DELETE |
| FK job_candidates → candidates | job_candidates | FK | `candidate_id` | CASCADE DELETE |
| FK evaluations → jobs | evaluations | FK | `job_id` | CASCADE DELETE |
| FK evaluations → candidates | evaluations | FK | `candidate_id` | CASCADE DELETE |
| FK rankings → jobs | rankings | FK | `job_id` | CASCADE DELETE |
| FK ranking_items → jobs | ranking_items | FK | `job_id` | CASCADE DELETE |
| `uq_eval_job_candidate` | evaluations | UNIQUE | `(job_id, candidate_id)` | — |
| `uq_ranking_item_per_version` | ranking_items | UNIQUE | `(job_id, ranking_version, candidate_id)` | — |

---

## Tamaños esperados

| Tabla | Filas esperadas (12 meses) | Tamaño/fila | Tamaño total |
|-------|---------------------------|-------------|--------------|
| candidates | 1,000 - 10,000 | ~2 KB | ~20 MB |
| jobs | 100 - 1,000 | ~1 KB | ~1 MB |
| job_candidates | 5,000 - 50,000 | ~0.5 KB | ~25 MB |
| evaluations | 5,000 - 50,000 | ~8-15 KB | ~400 MB |
| rankings | 100 - 1,000 | ~0.3 KB | ~0.3 MB |
| ranking_items | 10,000 - 100,000 | ~3-5 KB | ~300 MB |

**Límites PostgreSQL:**
- Filas por tabla: sin límite práctico
- Tamaño por fila: 1 GB (TOAST automático para JSONB grande)
- Índices: sin límite práctico

**Límites DynamoDB (referencia):**
- Tamaño por item: 400 KB
- Tamaño por tabla: sin límite
- Write capacity: 1 WCU = 1 write/s, 1 KB

---

## Notas de diseño

1. **UUID como PK:** Se usa `UUID` nativo de PostgreSQL con `gen_random_uuid()` (sin extensión adicional). Más eficiente que `TEXT` para PKs.

2. **JSONB para metadata:** `requirements`, `strengths`, `gaps` se mantienen como JSONB porque se consumen como documentos completos y no se filtran por contenido interno.

3. **CASCADE DELETE:** Si se elimina un job, se eliminan sus evaluaciones, asignaciones, rankings y ranking items automáticamente.

4. **ranking_items.candidate_id sin FK:** intentionally sin FK a `candidates` para permitir que un ranking snapshot sobreviva si el candidato es eliminado después del ranking.

5. **match_score como INTEGER vs REAL:** En `evaluations` es `INTEGER` (0-100). En `ranking_items` es `REAL` para permitir decimales en futuros modelos ML.

6. **Timestamps:** Todas las tablas usan `TIMESTAMPTZ` para evitar problemas de zona horaria.
