# Mapeo DynamoDB → PostgreSQL — AI Recruiter

> **Estado:** Documento de revisión. Placeholders `REEMPLAZAR_AQUI` indican valores que el equipo debe sustituir.
> **Fecha:** 2026-09-05
> **Versión:** 2.0

---

## 1. Inventario de tablas DynamoDB

### 1.1 `ai-recruiter-candidates`

| Atributo | Tipo DynamoDB | Rol | Descripción |
|----------|---------------|-----|-------------|
| `candidate_id` | `S` | **PK** | UUID v4 único del candidato |
| `owner_id` | `S` | Atributo | Cognito `sub` del propietario |
| `user_sub` | `S` | Atributo | Duplicado de `owner_id` (legacy) |
| `name` | `S` | Atributo | Nombre completo del candidato |
| `filename` | `S` | Atributo | Nombre del archivo CV (ej: `cv-{id}.pdf`) |
| `s3_location` | `S` | Atributo | URI S3 completa del CV |
| `metadata_location` | `S` | Atributo | URI S3 del JSON de metadata Bedrock |
| `ingestion_job_id` | `S` | Atributo | ID del job de ingestion de Bedrock |
| `ingestion_status` | `S` | Atributo | Estado de la ingestion |
| `indexed` | `BOOL` | Atributo | Si el CV ya fue indexado en Bedrock |

**Patrones de acceso:**
- `GetItem` por `candidate_id` → lectura directa
- `Scan` + `FilterExpression(owner_id)` → listar candidatos de un usuario
- `PutItem` → creación de candidato

**GSI:** Ninguno.

---

### 1.2 `ai-recruiter-jobs`

| Atributo | Tipo DynamoDB | Rol | Descripción |
|----------|---------------|-----|-------------|
| `job_id` | `S` | **PK** | UUID v4 único de la vacante |
| `owner_id` | `S` | Atributo | Cognito `sub` del propietario |
| `title` | `S` | Atributo | Título de la vacante |
| `description` | `S` | Atributo | Descripción completa (usada como prompt de Bedrock) |

**Patrones de acceso:**
- `GetItem` por `job_id` → lectura directa
- `Scan` + `FilterExpression(owner_id)` → listar vacantes de un usuario
- `PutItem` → creación de vacante

**GSI:** Ninguno.

---

### 1.3 `ai-recruiter-evaluations`

| Atributo | Tipo DynamoDB | Rol | Descripción |
|----------|---------------|-----|-------------|
| `job_id` | `S` | **PK** | ID de la vacante |
| `candidate_id` | `S` | **SK** | ID del candidato evaluado |
| `owner_id` | `S` | Atributo | Cognito `sub` del propietario |
| `job_title` | `S` | Atributo | Título de la vacante (denormalizado) |
| `job_description` | `S` | Atributo | Descripción de la vacante (denormalizado) |
| `candidate_name` | `S` | Atributo | Nombre del candidato (denormalizado) |
| `status` | `S` | Atributo | Estado: `PENDING`, `COMPLETED` |
| `evaluated_at` | `S` | Atributo | Timestamp ISO 8601 de la evaluación |
| `match_score` | `N` | Atributo | Puntaje 0-100 |
| `recommendation` | `S` | Atributo | `STRONG_MATCH`, `GOOD_MATCH`, `PARTIAL_MATCH`, `LOW_MATCH` |
| `requirements` | `S` | Atributo | JSON serializado: lista de `{requirement, status, evidence}` |
| `strengths` | `S` | Atributo | JSON serializado: lista de strings |
| `gaps` | `S` | Atributo | JSON serializado: lista de strings |
| `summary` | `S` | Atributo | Resumen textual de la evaluación |

**Patrones de acceso:**
- `Query` por `job_id` → evaluaciones de una vacante
- `GetItem` por `job_id` + `candidate_id` → evaluación específica
- `Scan` + `FilterExpression(owner_id)` → todas las evaluaciones de un usuario
- `PutItem` → crear/actualizar evaluación

**GSI:** Ninguno (pero se considera un GSI sobre `owner_id`).

---

### 1.4 `ai-recruiter-job-candidates`

| Atributo | Tipo DynamoDB | Rol | Descripción |
|----------|---------------|-----|-------------|
| `job_id` | `S` | **PK** | ID de la vacante |
| `candidate_id` | `S` | **SK** | ID del candidato asignado |
| `owner_id` | `S` | Atributo | Cognito `sub` del propietario |
| `status` | `S` | Atributo | `PENDING_EVALUATION`, `EVALUATED` |
| `assigned_at` | `S` | Atributo | Timestamp ISO 8601 de la asignación |

**Patrones de acceso:**
- `Query` por `job_id` + `FilterExpression(owner_id)` → candidatos de una vacante
- `GetItem` por `job_id` + `candidate_id` → verificar asignación
- `PutItem` → crear asignación
- `DeleteItem` por `job_id` + `candidate_id` → desasignar candidato
- `Query` por `job_id` + `FilterExpression(assigned_at > since)` → incremental mode

**GSI:** Ninguno (pero `owner_id` como GSI mejoraría el rendimiento del scope=all).

---

### 1.5 `ai-recruiter-rankings`

| Atributo | Tipo DynamoDB | Rol | Descripción |
|----------|---------------|-----|-------------|
| `job_id` | `S` | **PK** | ID de la vacante |
| `ranking_generated_at` | `S` | Atributo | Timestamp ISO 8601 del último ranking |
| `ranking_version` | `N` | Atributo | Versión incremental del ranking |

**Patrones de acceso:**
- `GetItem` por `job_id` → metadata del ranking
- `PutItem` → actualizar metadata después de recalculate

**GSI:** Ninguno.

---

## 2. Esquema relacional propuesto (DDL SQL)

```sql
-- ============================================================
-- ROLES / USUARIOS (Cognito sync)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_users (
    user_id         TEXT PRIMARY KEY,   -- Cognito sub
    email           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- CANDIDATES
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_candidates (
    candidate_id        TEXT PRIMARY KEY,
    owner_id            TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_users(user_id),
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

CREATE INDEX IF NOT EXISTS idx_candidates_owner
    ON REEMPLAZAR_AQUI_candidates (owner_id);

-- ============================================================
-- JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_jobs (
    job_id      TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_users(user_id),
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_owner
    ON REEMPLAZAR_AQUI_jobs (owner_id);

-- ============================================================
-- JOB ↔ CANDIDATE (tabla pivote)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_job_candidates (
    job_id          TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_jobs(job_id) ON DELETE CASCADE,
    candidate_id    TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_candidates(candidate_id) ON DELETE CASCADE,
    owner_id        TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_users(user_id),
    status          TEXT NOT NULL DEFAULT 'PENDING_EVALUATION',
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_job_candidates_candidate
    ON REEMPLAZAR_AQUI_job_candidates (candidate_id);

CREATE INDEX IF NOT EXISTS idx_job_candidates_owner
    ON REEMPLAZAR_AQUI_job_candidates (owner_id);

-- ============================================================
-- EVALUATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_evaluations (
    job_id              TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_jobs(job_id) ON DELETE CASCADE,
    candidate_id        TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_candidates(candidate_id) ON DELETE CASCADE,
    owner_id            TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_users(user_id),
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

CREATE INDEX IF NOT EXISTS idx_evaluations_candidate
    ON REEMPLAZAR_AQUI_evaluations (candidate_id);

CREATE INDEX IF NOT EXISTS idx_evaluations_owner
    ON REEMPLAZAR_AQUI_evaluations (owner_id);

CREATE INDEX IF NOT EXISTS idx_evaluations_score
    ON REEMPLAZAR_AQUI_evaluations (match_score DESC);

CREATE INDEX IF NOT EXISTS idx_evaluations_recommendation
    ON REEMPLAZAR_AQUI_evaluations (recommendation);

CREATE INDEX IF NOT EXISTS idx_evaluations_job_score
    ON REEMPLAZAR_AQUI_evaluations (job_id, match_score DESC);

-- ============================================================
-- RANKINGS
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_rankings (
    job_id                  TEXT PRIMARY KEY REFERENCES REEMPLAZAR_AQUI_jobs(job_id) ON DELETE CASCADE,
    ranking_generated_at    TIMESTAMPTZ,
    ranking_version         INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- RANKING ITEMS (snapshots de cada ranking run)
-- ============================================================

CREATE TABLE IF NOT EXISTS REEMPLAZAR_AQUI_ranking_items (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES REEMPLAZAR_AQUI_jobs(job_id) ON DELETE CASCADE,
    candidate_id    TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_ranking_items_job
    ON REEMPLAZAR_AQUI_ranking_items (job_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ranking_item_per_version
    ON REEMPLAZAR_AQUI_ranking_items (job_id, ranking_version, candidate_id);
```

---

## 3. Decisión JSONB vs Normalización

### Campos que se mantienen en JSONB

| Campo | Tabla | Razón |
|-------|-------|-------|
| `requirements` | evaluations | Lista heterogénea de objetos `{requirement, status, evidence}`. Se lee/escribe como documento completo; no se filtra por contenido interno en queries frecuentes. |
| `strengths` | evaluations, ranking_items | Lista simple de strings. Se consume como bloque; no se busca por elemento individual. |
| `gaps` | evaluations, ranking_items | Ídem `strengths`. |

### Campos que se normalizan (columnas nativas)

| Campo | Tabla | Razón |
|-------|-------|-------|
| `match_score` | evaluations, ranking_items | Se filtra, ordena y agrega frecuentemente (`ORDER BY match_score DESC`). Índice B-tree nativo. |
| `recommendation` | evaluations, ranking_items | Dominio cerrado, se filtra por valor exacto. Índice B-tree nativo. |
| `owner_id` | todas | Se filtra en casi todos los queries. Índice B-tree nativo. |
| `assigned_at` | job_candidates | Se usa en el modo incremental (`assigned_at > since`). Índice B-tree nativo. |
| `ranking_version` | rankings, ranking_items | Se usa para identificar el ranking más reciente y recuperar items. |

### Justificación resumen

```
┌──────────────────────────────────────────────────────────────┐
│  CRITERIO              │  JSONB           │  COLUMNA NATIVA  │
├──────────────────────────────────────────────────────────────┤
│  Lectura documento     │  ✓ Rápido        │  ✗ Requiere JOIN │
│  Filtrado por contenido│  ✗ GIN index     │  ✓ B-tree index  │
│  Ordenamiento          │  ✗ No indexable  │  ✓ ASC/DESC      │
│  Agregación (SUM/AVG)  │  ✗ No posible    │  ✓ Nativo        │
│  Volúmenes < 10K       │  ✓ Suficiente    │  ✓ Overkill      │
│  Flexibilidad schema   │  ✓ Sin migración │  ✗ ALTER TABLE   │
└──────────────────────────────────────────────────────────────┘
```

**Conclusión:** JSONB para `requirements/strengths/gaps` (documents consumidos completos). Columnas nativas para todo lo que se filtra, ordena o agrega.

---

## 4. Consultas frecuentes e índices

### 4.1 Listar jobs de un usuario

**DynamoDB (actual):**
```python
response = jobs_table.scan()
user_jobs = [j for j in response.get("Items", []) if j["owner_id"] == owner_id]
```

**PostgreSQL:**
```sql
SELECT job_id, title, description, created_at
FROM REEMPLAZAR_AQUI_jobs
WHERE owner_id = $1
ORDER BY created_at DESC;
```

**Índice:** `idx_jobs_owner` (ya cubierto).

---

### 4.2 Ranking de candidatos para un job

**DynamoDB (actual):** Scan de `candidates_table` + query de `evaluations_table` + filtrado en Python.

**PostgreSQL:**
```sql
SELECT
    e.candidate_id,
    c.name                              AS candidate_name,
    e.match_score,
    e.recommendation,
    e.strengths,
    e.gaps,
    ROW_NUMBER() OVER (
        ORDER BY e.match_score DESC, c.name ASC
    ) AS rank
FROM REEMPLAZAR_AQUI_evaluations e
JOIN REEMPLAZAR_AQUI_candidates c ON c.candidate_id = e.candidate_id
WHERE e.job_id = $1
  AND e.match_score >= $2          -- min_score
  AND e.match_score <= $3          -- max_score
  AND ($4::TEXT IS NULL OR e.recommendation = $4)
ORDER BY e.match_score DESC, c.name ASC
LIMIT $5 OFFSET $6;
```

**Índice:** `idx_evaluations_job_score` cubre el ORDER BY.

```sql
CREATE INDEX IF NOT EXISTS idx_evaluations_job_score
    ON REEMPLAZAR_AQUI_evaluations (job_id, match_score DESC);
```

---

### 4.3 Candidatos pendientes de evaluación

**DynamoDB (actual):**
```python
assigned_ids = get_job_candidate_ids(job_id, owner_id)
evaluations_by_candidate = {e["candidate_id"]: e for e in evaluations}
pending = [id for id in assigned_ids if id not in evaluations_by_candidate]
```

**PostgreSQL:**
```sql
SELECT c.candidate_id, c.name
FROM REEMPLAZAR_AQUI_job_candidates jc
JOIN REEMPLAZAR_AQUI_candidates c ON c.candidate_id = jc.candidate_id
LEFT JOIN REEMPLAZAR_AQUI_evaluations e
    ON e.job_id = jc.job_id AND e.candidate_id = jc.candidate_id
WHERE jc.job_id = $1
  AND jc.owner_id = $2
  AND e.candidate_id IS NULL;
```

**Índice:** PRIMARY KEY `(job_id, candidate_id)` ya cubierto.

---

### 4.4 Incremental: candidatos nuevos desde último ranking

**DynamoDB (actual):**
```python
FilterExpression=Attr("assigned_at").gt(since)
```

**PostgreSQL:**
```sql
SELECT jc.candidate_id, c.name
FROM REEMPLAZAR_AQUI_job_candidates jc
JOIN REEMPLAZAR_AQUI_candidates c ON c.candidate_id = jc.candidate_id
LEFT JOIN REEMPLAZAR_AQUI_evaluations e
    ON e.job_id = jc.job_id AND e.candidate_id = jc.candidate_id
WHERE jc.job_id = $1
  AND jc.owner_id = $2
  AND jc.assigned_at > (
      SELECT ranking_generated_at
      FROM REEMPLAZAR_AQUI_rankings
      WHERE job_id = $1
  )
  AND e.candidate_id IS NULL;
```

**Índice:** `idx_job_candidates_owner` + `assigned_at` en la PRIMARY KEY.

---

### 4.5 Filtrar evaluaciones por recomendación

**PostgreSQL:**
```sql
SELECT candidate_id, candidate_name, match_score, recommendation
FROM REEMPLAZAR_AQUI_evaluations
WHERE job_id = $1
  AND recommendation = $2
ORDER BY match_score DESC;
```

**Índice:** `idx_evaluations_recommendation` + `idx_evaluations_job_score` (composite).

---

### 4.6 Obtener ranking metadata

**DynamoDB (actual):**
```python
rankings_table.get_item(Key={"job_id": job_id})
```

**PostgreSQL:**
```sql
SELECT ranking_generated_at, ranking_version
FROM REEMPLAZAR_AQUI_rankings
WHERE job_id = $1;
```

**Índice:** PRIMARY KEY `job_id` (ya cubierto).

---

### 4.7 Actualizar ranking metadata

**DynamoDB (actual):**
```python
rankings_table.put_item(Item={...})
```

**PostgreSQL:**
```sql
INSERT INTO REEMPLAZAR_AQUI_rankings (job_id, ranking_generated_at, ranking_version)
VALUES ($1, now(), $2)
ON CONFLICT (job_id)
DO UPDATE SET
    ranking_generated_at = now(),
    ranking_version = $2;
```

---

### 4.8 Resumen de índices

| Tabla | Índice | Columnas | Justificación |
|-------|--------|----------|---------------|
| `candidates` | `idx_candidates_owner` | `owner_id` | Listado por usuario |
| `jobs` | `idx_jobs_owner` | `owner_id` | Listado por usuario |
| `job_candidates` | `idx_job_candidates_candidate` | `candidate_id` | Búsqueda inversa |
| `job_candidates` | `idx_job_candidates_owner` | `owner_id` | Scope `all` |
| `evaluations` | `idx_evaluations_candidate` | `candidate_id` | Historial por candidato |
| `evaluations` | `idx_evaluations_owner` | `owner_id` | Scope `all` |
| `evaluations` | `idx_evaluations_score` | `match_score DESC` | Ranking sin job_id |
| `evaluations` | `idx_evaluations_recommendation` | `recommendation` | Filtro por clasificación |
| `evaluations` | `idx_evaluations_job_score` | `(job_id, match_score DESC)` | **Índice principal del ranking** |
| `ranking_items` | `idx_ranking_items_job` | `job_id` | Recuperar items por job |
| `ranking_items` | `uq_ranking_item_per_version` | `(job_id, ranking_version, candidate_id)` | Integridad + lookup |

---

## 5. Riesgos y recomendaciones

### 5.1 Consistencia

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| **DynamoDB → PG dual-write** durante cutover | Datos inconsistentes entre stores | Usar DMS con CDC, o cutover big-bang con ventana de mantenimiento |
| **Transacciones cross-table** en DynamoDB (no existen) | Evaluaciones huérfanas sin job | En PG: FK con `ON DELETE CASCADE` garantiza integridad referencial |
| **Concurrencia en ranking recalculate** | Doble cálculo del mismo ranking | Advisory lock `pg_advisory_lock(sha256(job_id)[:8])` en PostgreSQL |

### 5.2 Tamaño de filas

| Tabla | DynamoDB | PostgreSQL | Notas |
|-------|----------|------------|-------|
| `candidates` | ~1 KB/item | ~2 KB/row | Sin cambio significativo |
| `jobs` | ~0.5 KB/item | ~1 KB/row | `description` puede ser largo |
| `evaluations` | ~5-10 KB/item | ~8-15 KB/row | `requirements` JSONB puede crecer |
| `job_candidates` | ~0.3 KB/item | ~0.5 KB/row | Tabla pivote ligera |
| `rankings` | ~0.2 KB/item | ~0.3 KB/row | Solo metadata |
| `ranking_items` | N/A (nueva) | ~3-5 KB/row | Snapshot por versión |

**Límite DynamoDB:** 400 KB/item. **Límite PostgreSQL:** 1 GB/row (TOAST para JSONB grande).

**Recomendación:** Ninguna tabla se acerca al límite de DynamoDB. PostgreSQL maneja filas grandes sin problemas.

### 5.3 Rendimiento

| Escenario | DynamoDB | PostgreSQL | Mejora esperada |
|-----------|----------|------------|-----------------|
| Scan completo de evaluations | ~5-10s (con 10K items) | ~50ms (con idx) | **100-200x** |
| Ranking con ORDER BY + LIMIT | Scan + Python sort | Index scan | **50-100x** |
| Conteo de pending candidates | Scan + filter | LEFT JOIN + count | **20-50x** |
| Filtro por recommendation | Scan + filter | Index scan | **100x** |

### 5.4 Migración

| Fase | Riesgo | Recomendación |
|------|--------|---------------|
| **Export DynamoDB** | Datos parciales si export falla | Verificar conteo post-export |
| **Import PostgreSQL** | Violación de FK si el orden es incorrecto | Migrar en orden: users → candidates → jobs → job_candidates → evaluations → rankings |
| **Dual-write** | Latencia adicional | Implementar solo si es necesario; preferir cutover big-bang |
| **Rollback** | Datos en PG se pierden | DynamoDB permanece intacto; PG se trunca y se vuelve a DynamoDB |

### 5.5 Costos estimados

| Componente | DynamoDB (actual) | PostgreSQL (RDS) | Ahorro |
|------------|-------------------|-------------------|--------|
| **Reads** | ~$0.25/million RRU | Incluido en instancia | ~$0.20/mes |
| **Writes** | ~$1.25/million WCU | Incluido en instancia | ~$1.00/mes |
| **Storage** | ~$0.25/GB-mes | ~$0.10/GB-mes (gp3) | ~$0.15/GB-mes |
| **Instancia** | N/A | ~$15-50/mes (db.t3.micro) | Costo adicional |

**Conclusión:** Para volúmenes actuales (< 100K items), el costo de PostgreSQL es comparable. La ventaja está en consultas complejas y consistencia transaccional.

---

## 6. Placeholders a reemplazar

| Placeholder | Tipo | Ejemplo |
|-------------|------|---------|
| `REEMPLAZAR_AQUI_users` | Tabla | `ai_recruiter_users` |
| `REEMPLAZAR_AQUI_candidates` | Tabla | `ai-recruiter-candidates-pg` |
| `REEMPLAZAR_AQUI_jobs` | Tabla | `ai-recruiter-jobs-pg` |
| `REEMPLAZAR_AQUI_job_candidates` | Tabla | `ai-recruiter-job-candidates-pg` |
| `REEMPLAZAR_AQUI_evaluations` | Tabla | `ai-recruiter-evaluations-pg` |
| `REEMPLAZAR_AQUI_rankings` | Tabla | `ai-recruiter-rankings-pg` |
| `REEMPLAZAR_AQUI_ranking_items` | Tabla | `ai-recruiter-ranking-items-pg` |
