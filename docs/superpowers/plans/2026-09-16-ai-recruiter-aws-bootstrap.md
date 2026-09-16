# AI Recruiter AWS Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy AI Recruiter into AWS account `890876258895` in `us-east-2` using the repository's existing low-cost Lightsail architecture, while removing stale dependencies on the previous AWS account.

**Architecture:** Keep the existing single-host production topology: one Lightsail Micro instance runs PostgreSQL plus Docker containers for API, worker, and frontend. AWS-managed components remain ECR, Cognito, S3, SQS/DLQ, Bedrock Knowledge Base, S3 Vectors, Secrets Manager, IAM, and GitHub OIDC. Runtime AWS access uses IAM Roles Anywhere rather than IAM user access keys.

**Tech Stack:** AWS Lightsail, ECR, Cognito User Pools, S3, S3 Vectors, SQS, CloudFormation, Bedrock/Nova Lite, Bedrock Knowledge Bases, IAM Roles Anywhere, Secrets Manager, GitHub Actions OIDC, Docker, PostgreSQL, FastAPI, React/Vite.

**Spec:** `docs/superpowers/specs/2026-09-16-candidate-ingestion-core-design.md` plus the existing production deployment contract in `.github/workflows/deploy.yml`.

## Global Constraints

- Region is `us-east-2`.
- Target AWS account is `890876258895`.
- Production host remains Lightsail to keep fixed monthly cost low.
- Use Lightsail `micro_3_0` (1 GiB RAM, 40 GiB disk, IPv4) rather than Nano because API + worker + PostgreSQL must coexist.
- No long-lived IAM user access keys may be embedded in the app, host, repository, or GitHub secrets.
- Runtime AWS access uses `AiRecruiterBedrockRuntimeRole` through IAM Roles Anywhere.
- GitHub deploy access uses OIDC and `AiRecruiterGithubDeployRole`.
- SSH private key and Roles Anywhere client material are stored in AWS Secrets Manager, not committed to GitHub.
- Candidate source documents are private and encrypted at rest; staging data expires automatically.
- Bedrock model is `amazon.nova-lite-v1:0` unless the application is explicitly migrated later.
- Bedrock KB embedding model is `amazon.titan-embed-text-v2:0`.
- Bedrock vector store is S3 Vectors.
- Real candidate CVs contain personal data; only a synthetic non-PII bootstrap document may be used for initial KB validation.
- Do not modify or delete the cotizador resources already present in this AWS account.

---

### Task 1: Make deployment configuration account-portable

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Modify: `scripts/deploy-api.sh`
- Modify: `scripts/deploy-worker.sh`
- Modify: `app/infrastructure/bedrock/config.py`
- Modify: `app/infrastructure/imports/ingestion.py`
- Modify: `app/infrastructure/imports/storage.py`
- Test: `app/tests/test_deploy_contract.py`
- Test: `app/tests/test_candidate_import_deploy.py`
- Test: `app/tests/test_config.py`

**Interfaces:**
- Consumes environment variables `AWS_ACCOUNT_ID`, `KNOWLEDGE_BASE_ID`, `DATA_SOURCE_ID`, `S3_BUCKET`, `COGNITO_USER_POOL_ID`, and `COGNITO_CLIENT_ID`.
- Produces deploy scripts/workflow that do not depend on account `765761474007`, KB `VUGNMJQAEN`, data source `P8SUL2VFHA`, bucket `ai-cv-rag-adrian-2026`, or CloudFront distribution `E1IBIX4EWENEP7`.

- [ ] **Step 1: Write failing deployment-contract tests**

```python
def test_deploy_has_no_previous_account_or_resource_ids():
    text = Path('.github/workflows/deploy.yml').read_text() + Path('scripts/deploy-api.sh').read_text() + Path('scripts/deploy-worker.sh').read_text()
    for stale in ('765761474007', 'VUGNMJQAEN', 'P8SUL2VFHA', 'E1IBIX4EWENEP7'):
        assert stale not in text
```

- [ ] **Step 2: Run RED verification**

Run: `python -m pytest app/tests/test_deploy_contract.py app/tests/test_candidate_import_deploy.py app/tests/test_config.py -q`

Expected: FAIL because stale account/resource IDs are currently embedded.

- [ ] **Step 3: Implement environment-driven deployment**

Use runtime variables instead of old literals. `.github/workflows/deploy.yml` must assume `arn:aws:iam::890876258895:role/AiRecruiterGithubDeployRole`, obtain account/resource identifiers from CloudFormation/Secrets Manager where possible, and pass `S3_BUCKET`, `KNOWLEDGE_BASE_ID`, `DATA_SOURCE_ID`, Cognito IDs, and import queue/bucket into API and worker deploy scripts.

- [ ] **Step 4: Run GREEN verification**

Run: `python -m pytest app/tests/test_deploy_contract.py app/tests/test_candidate_import_deploy.py app/tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `infra: make production deployment account portable`

---

### Task 2: Provision IAM, ECR, Cognito, and secure bootstrap material

**AWS resources:**
- ECR repositories: `ai-recruiter-api`, `ai-recruiter-frontend`
- Cognito pool: `ai-recruiter-users`
- Cognito app client: `ai-recruiter-web`
- GitHub OIDC provider: `token.actions.githubusercontent.com`
- Deploy role: `AiRecruiterGithubDeployRole`
- Runtime role: `AiRecruiterBedrockRuntimeRole`
- Roles Anywhere trust anchor/profile for runtime role
- Secrets Manager: `/ai-recruiter/prod/lightsail-ssh-key`, `/ai-recruiter/prod/rolesanywhere-client-cert`, `/ai-recruiter/prod/rolesanywhere-client-key`

- [ ] **Step 1: Create/read resources idempotently using AWS APIs**
- [ ] **Step 2: Attach least-privilege policies needed by GitHub deploy and runtime containers**
- [ ] **Step 3: Verify trust policies, role ARNs, Cognito IDs, and ECR URIs**

Expected verification: all resources resolve in account `890876258895` and no static AWS access key is created.

---

### Task 3: Provision candidate document, queue, and Bedrock RAG infrastructure

**AWS resources:**
- Canonical candidate S3 bucket: account-unique `ai-recruiter-candidates-890876258895-us-east-2`
- Candidate import CloudFormation stack: `ai-recruiter-candidate-import`
- S3 Vector bucket/index for Bedrock KB
- Bedrock KB: `ai-recruiter-candidates`
- Bedrock data source scoped to canonical bucket prefix `documents/`

- [ ] **Step 1: Create canonical S3 bucket with public access blocked, encryption, and versioning**
- [ ] **Step 2: Deploy `infra/candidate-import.yml` using `AiRecruiterBedrockRuntimeRole`**
- [ ] **Step 3: Create S3 Vectors bucket/index and KB service role**
- [ ] **Step 4: Upload a synthetic non-PII bootstrap document under `documents/`**
- [ ] **Step 5: Create KB/data source with fixed-size chunking suitable for resumes**
- [ ] **Step 6: Start ingestion, poll to terminal state, and run retrieval verification**
- [ ] **Step 7: Remove bootstrap document and resync after the real first candidate is ingested**

Expected verification: KB retrieval returns the synthetic bootstrap document before production data is accepted.

---

### Task 4: Provision and bootstrap the Lightsail production host

**AWS resources:**
- Key pair: `ai-recruiter-prod`
- Instance: `ai-recruiter-micro-prod`
- Static IP: `ai-recruiter-prod-ip`
- Blueprint: `ubuntu_24_04`
- Bundle: `micro_3_0`

- [ ] **Step 1: Create key pair and immediately store private material in Secrets Manager**
- [ ] **Step 2: Create Lightsail instance in `us-east-2a` with Docker/PostgreSQL bootstrap user data**
- [ ] **Step 3: Allocate and attach static IPv4 address**
- [ ] **Step 4: Configure firewall for SSH, HTTP, and HTTPS only**
- [ ] **Step 5: Verify instance is running and PostgreSQL/Docker bootstrap completed**

Expected verification: instance has a stable IPv4 address and accepts production deployment.

---

### Task 5: Deploy containers and verify production without DNS dependency

**Interfaces:**
- GitHub Actions pushes immutable SHA-tagged ECR images.
- GitHub OIDC retrieves bootstrap secrets and deploys via SSH.
- API/worker receive Cognito, S3, SQS, KB, data source, and Roles Anywhere configuration.

- [ ] **Step 1: Build backend/frontend containers through the production workflow**
- [ ] **Step 2: Run Alembic migrations against host PostgreSQL**
- [ ] **Step 3: Start API, worker, and frontend containers**
- [ ] **Step 4: Verify `/api/health`, frontend HTML, Cognito configuration, S3/SQS access, Bedrock identity, KB retrieval, and worker liveness**
- [ ] **Step 5: Record the static-IP endpoint for temporary access**

Expected verification: the complete app works from the Lightsail IP before DNS/CloudFront is introduced.

---

### Task 6: DNS/TLS and Gmail follow-up gate

**Files/Systems:**
- DNS provider for `adrianguerra.net`
- Optional CloudFront or Lightsail TLS front door
- Google OAuth configuration
- AWS Secrets Manager Gmail OAuth secret

- [ ] **Step 1: Determine the authoritative DNS provider for `adrianguerra.net`**
- [ ] **Step 2: Point `air.adrianguerra.net` (or the agreed canonical hostname) to the production front door**
- [ ] **Step 3: Enable HTTPS and verify `/api/auth/me` routing**
- [ ] **Step 4: Complete the user-authorized Google OAuth browser step**
- [ ] **Step 5: Store Gmail OAuth refresh material in Secrets Manager and enable Gmail ingestion**

Expected verification: public HTTPS application works and Gmail ingestion can be enabled without credentials in GitHub or source code.
