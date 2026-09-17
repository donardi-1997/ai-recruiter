# AI Recruiter — ASIATI Talent Intelligence

Plataforma de reclutamiento para gestionar vacantes, candidatos e ingestión de hojas de vida, con evaluación y ranking asistidos por inteligencia artificial sobre AWS.

La aplicación centraliza el flujo de selección: recibe candidatos por carga manual, importación masiva e integraciones; almacena los documentos de forma duradera; los indexa en Amazon Bedrock Knowledge Bases; y genera evaluaciones versionadas con fortalezas, brechas, evidencia y ranking por vacante.

**Aplicación actual:** http://3.23.27.223

**Health check:** http://3.23.27.223/api/health

> El entorno actual utiliza una IP estática de Lightsail y HTTP mientras se define el dominio corporativo. El workload productivo se mantiene en `us-east-2`.

## Funcionalidades principales

- Registro con Amazon Cognito y confirmación administrativa automática; no requiere código de verificación por correo.
- Inicio de sesión y aislamiento de datos por propietario autenticado.
- Gestión de vacantes con perfil estructurado de evaluación y enriquecimiento asistido por IA.
- Gestión de candidatos y asignación a vacantes.
- Carga individual de CV y descarga controlada de documentos.
- Importación masiva de PDF/DOCX/ZIP mediante S3 + SQS + worker asíncrono.
- Resolución de identidad de candidatos y deduplicación por señales fuertes.
- Ingesta de documentos en Amazon Bedrock Knowledge Bases.
- Recuperación semántica mediante S3 Vectors.
- Evaluación versionada de candidatos con Amazon Nova Lite.
- Re-evaluación automática cuando cambia información relevante de una vacante.
- Ranking por vacante con estados de evaluación y materialización persistente.
- Integración con Indeed para publicación/sincronización y recuperación de candidatos.
- Integración Gmail corporativa OAuth para recibir CVs desde un único buzón compartido.
- Sincronización Gmail completa e incremental mediante `historyId`.
- Filtros seguros de correo para evitar escanear indiscriminadamente todo el buzón.

## Arquitectura de producción

```mermaid
flowchart TD
    U[Usuario] --> N[Nginx / React]
    N --> API[FastAPI API]

    subgraph LS[Amazon Lightsail - us-east-2]
        N
        API
        W[Worker asíncrono]
        PG[(PostgreSQL local)]
    end

    API --> COG[Amazon Cognito]
    API --> S3[S3 candidatos]
    API --> SQ[SQS]
    W --> SQ
    W --> S3
    API --> KB[Bedrock Knowledge Base]
    W --> KB
    KB --> VEC[S3 Vectors]
    API --> NOVA[Amazon Nova Lite]
    W --> NOVA

    GH[GitHub Actions] -->|OIDC| AWS[AWS IAM]
    LS -->|Roles Anywhere| AWS

    GOOGLE[Google OAuth] --> APIGW[API Gateway HTTP API - us-east-2]
    APIGW --> API
    API --> SM[Secrets Manager]
```

### Runtime

La producción se ejecuta en una instancia Lightsail `ai-recruiter-micro-prod` en `us-east-2` con IP estática. Docker ejecuta tres componentes principales:

- `ai-recruiter-web`: Nginx + SPA React.
- `ai-recruiter-api`: FastAPI.
- `ai-recruiter-worker`: procesamiento asíncrono de importaciones, ingestión y re-evaluaciones.

PostgreSQL se ejecuta localmente en la misma instancia Lightsail. No se utiliza Amazon RDS en la arquitectura productiva actual.

### Identidad AWS

- GitHub Actions obtiene credenciales temporales mediante GitHub OIDC.
- La instancia Lightsail usa IAM Roles Anywhere para consumir AWS sin access keys persistentes.
- API y worker usan el rol `AiRecruiterBedrockRuntimeRole`.
- Las imágenes se publican en Amazon ECR.

## Gmail corporativo

La primera versión admite **una sola cuenta Gmail corporativa compartida**.

Desde **Integraciones** el usuario puede:

1. Consultar el estado de la integración.
2. Iniciar OAuth con Google.
3. Ver qué buzón corporativo está conectado.
4. Ejecutar una sincronización manual.
5. Desconectar el buzón.

La aplicación solicita únicamente el scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Los secretos OAuth nunca se envían al frontend. `client_id`, `client_secret`, `refresh_token`, configuración operativa y el secreto de firma de `state` se administran mediante AWS Secrets Manager.

El callback HTTPS de producción se expone mediante un HTTP API regional en `us-east-2`:

```text
https://3fkmecjfig.execute-api.us-east-2.amazonaws.com/api/integrations/gmail/oauth/callback
```

Ese URI debe registrarse exactamente como **Authorized redirect URI** en el cliente OAuth Web de Google Cloud.

### Endpoints Gmail

| Endpoint | Uso |
| --- | --- |
| `GET /api/integrations/gmail/status` | Estado y metadata pública de la integración |
| `GET /api/integrations/gmail/oauth/start` | Construye la autorización Google con `state` firmado |
| `GET /api/integrations/gmail/oauth/callback` | Callback protegido por `state` HMAC temporal |
| `POST /api/integrations/gmail/sync` | Sincronización manual del buzón |
| `DELETE /api/integrations/gmail` | Elimina el grant del buzón conservando el cliente OAuth |

La sincronización solo se habilita cuando existe un filtro seguro mediante `allowed_senders` o una consulta Gmail explícita con `from:`.

## Flujo de candidatos

```text
Fuente
  ├─ carga individual
  ├─ importación masiva
  ├─ Indeed
  └─ Gmail corporativo
        ↓
Candidate Ingestion Core
        ↓
S3 / persistencia duradera
        ↓
SQS + worker
        ↓
resolución de identidad
        ↓
asignación a vacante
        ↓
Bedrock Knowledge Base / S3 Vectors
        ↓
evaluación versionada
        ↓
ranking
```

## Stack

### Frontend

- React 19
- Vite
- React Router
- Axios
- CSS

### Backend

- Python 3.10
- FastAPI
- Uvicorn
- SQLAlchemy
- Alembic
- PostgreSQL
- Boto3
- LangChain AWS
- HTTPX

### AWS

- Amazon Lightsail
- Amazon ECR
- Amazon Cognito
- Amazon S3
- Amazon SQS
- Amazon Bedrock
- Bedrock Knowledge Bases
- S3 Vectors
- AWS Secrets Manager
- API Gateway HTTP API
- IAM Roles Anywhere
- GitHub OIDC
- AWS CloudFormation

## Estructura

```text
ai-recruiter/
├── .github/workflows/       # CI/CD y bootstrap de producción
├── app/
│   ├── domains/             # Lógica de candidatos, vacantes, ranking e ingestión
│   ├── infrastructure/      # AWS, storage, OAuth y persistencia externa
│   ├── integrations/        # Adaptadores Gmail/Indeed y otras fuentes
│   ├── tests/               # Tests backend y contratos de despliegue
│   └── main.py
├── frontend-react/
│   └── src/
│       ├── api/
│       ├── auth/
│       ├── components/
│       └── pages/
├── infra/                   # CloudFormation
├── scripts/                 # Deploy, worker y operaciones
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Desarrollo local

### Backend

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Variables mínimas de ejemplo:

```dotenv
AWS_REGION=us-east-2
COGNITO_USER_POOL_ID=<user-pool-id>
COGNITO_CLIENT_ID=<app-client-id>
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_recruiter
```

Para Gmail local pueden utilizarse variables `GMAIL_*`; en producción la configuración se superpone desde Secrets Manager.

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Endpoints locales útiles:

- Swagger: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`
- Health: `http://localhost:8000/api/health`

### Frontend

```powershell
cd frontend-react
npm ci
npm run dev
```

Por defecto Vite queda disponible en `http://localhost:5173`.

## Validación

Backend:

```powershell
python -m pytest app/tests/ -v
```

Frontend:

```powershell
cd frontend-react
npm run lint
npm test
npm run build
```

CI también ejecuta un smoke test de PostgreSQL que aplica Alembic hasta `head` y valida el esquema resultante.

## Despliegue

Los cambios pasan por GitHub Actions antes de producción:

1. Tests backend y frontend.
2. Smoke de PostgreSQL/Alembic.
3. Autenticación GitHub → AWS mediante OIDC.
4. Build de imágenes backend/frontend.
5. Push a ECR con tag inmutable por SHA.
6. Migraciones antes de reemplazar la API.
7. Deploy API + worker + frontend en Lightsail.
8. Health checks locales y públicos.
9. Promoción del artefacto validado.

La instancia obtiene permisos AWS mediante Roles Anywhere; no se almacenan access keys permanentes en GitHub ni dentro de las imágenes.

## Seguridad

- JWT de Cognito en endpoints autenticados.
- Registro Cognito autoconfirmado por backend para evitar flujo de confirmación por correo.
- Aislamiento de datos por `owner_sub`.
- OAuth Gmail protegido con `state` firmado y expiración corta.
- Refresh tokens y client secret fuera de Git y fuera del navegador.
- Filtro de Gmail obligatorio antes de sincronizar.
- S3 privado y URLs firmadas de corta duración cuando aplica.
- SQS con procesamiento idempotente y recuperación de trabajos.
- Roles Anywhere para credenciales temporales del host.
- GitHub OIDC para CI/CD sin access keys persistentes.

## Estado actual de Gmail OAuth

La infraestructura del callback y Secrets Manager puede existir antes de cargar las credenciales Google. Mientras `client_id` y `client_secret` estén vacíos, la pantalla **Integraciones** muestra Gmail como no configurado y mantiene la sincronización bloqueada de forma segura.

Para activar la integración deben configurarse el cliente OAuth Web de Google y un filtro real del buzón corporativo. No se deben inventar remitentes ni ampliar la consulta a todo el buzón.

## Licencia

Este repositorio no declara una licencia. Añade un archivo `LICENSE` antes de permitir redistribución o uso por terceros.
