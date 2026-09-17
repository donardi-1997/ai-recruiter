# Indeed Resume Windows Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small Windows desktop agent for Katherine's workstation that consumes one leased Indeed resume task at a time, reuses a dedicated local Microsoft Edge session, downloads the CV without storing Indeed credentials, uploads the validated PDF to the AI Recruiter backend, and pauses safely for manual login/MFA/CAPTCHA when necessary.

**Architecture:** Keep the Windows client independent from the FastAPI server package. A thin API client talks only to `/api/agents/indeed-resume/*`. The raw machine token lives in Windows Credential Manager. A visible Playwright persistent browser context uses a dedicated profile under `%LOCALAPPDATA%\ASIATI\ResumeAgent\browser-profile`. The worker loop is sequential: claim -> obtain PDF or request human intervention -> upload -> next task. A small Tkinter UI runs the worker on a background thread and shows queue/session state. CI mocks browser and network behavior; no CI job logs in to Indeed.

**Tech Stack:** Python 3.12+, httpx, Playwright Python with installed Microsoft Edge (`channel="msedge"`), keyring/Windows Credential Manager, Tkinter, pytest, PyInstaller for the final Windows distribution.

**Spec:** `docs/superpowers/specs/2026-09-17-indeed-email-resume-agent-design.md`

**Backend dependency:** `docs/superpowers/plans/2026-09-17-indeed-email-resume-backend.md`

## Global Constraints

- The agent never asks for or stores an Indeed password.
- It never copies Katherine's normal Chrome/Edge profile. It owns a dedicated persistent profile.
- It never automates CAPTCHA or MFA. Login/challenge detection returns `NEEDS_HUMAN`.
- One task at a time; no parallel tabs/workers in the MVP.
- The machine token is stored only through Windows Credential Manager/keyring, never `.env`, JSON config, source code or logs.
- The lease token is kept only in process memory for the active task and is never written to disk or logs.
- The non-secret API base URL is configurable. Production default is `https://dzcwl3yhv133t.cloudfront.net` and requests use `/api/agents/indeed-resume/...` through the existing HTTPS origin/proxy path.
- Local PDF validation is defense in depth only. The backend remains authoritative and validates PDF magic/type/size again.
- Maximum local PDF size is 15 MiB.
- Browser automation is fail-closed: if the UI does not match a known deterministic download path, mark `NEEDS_HUMAN` rather than clicking speculative controls.
- TDD is mandatory. Every code task below starts with a failing test, runs RED, implements minimal behavior, runs GREEN, and commits.

---

### Task 1: Create the agent package, non-secret config, and Windows credential storage

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/indeed_resume_agent/__init__.py`
- Create: `tools/indeed_resume_agent/config.py`
- Create: `tools/indeed_resume_agent/credential_store.py`
- Create: `tools/indeed_resume_agent/setup_token.py`
- Create: `tools/indeed_resume_agent/requirements.txt`
- Create: `tools/indeed_resume_agent/tests/__init__.py`
- Create: `tools/indeed_resume_agent/tests/test_config.py`
- Create: `tools/indeed_resume_agent/tests/test_credential_store.py`

**Non-secret config contract:**

```python
@dataclass(frozen=True)
class AgentConfig:
    api_base_url: str
    browser_profile_dir: Path
    request_timeout_seconds: float = 30.0
    heartbeat_interval_seconds: float = 120.0
    idle_poll_seconds: float = 10.0
    max_pdf_bytes: int = 15 * 1024 * 1024


def load_config(*, environ: Mapping[str, str] | None = None) -> AgentConfig:
    ...
```

Defaults on Windows:

```text
api_base_url=https://dzcwl3yhv133t.cloudfront.net
browser_profile_dir=%LOCALAPPDATA%\ASIATI\ResumeAgent\browser-profile
request_timeout_seconds=30
heartbeat_interval_seconds=120
idle_poll_seconds=10
```

Credential contract:

```python
SERVICE_NAME = "ASIATI Resume Agent"
USERNAME = "agent-token"

def read_agent_token() -> str: ...
def write_agent_token(token: str) -> None: ...
def delete_agent_token() -> None: ...
```

- [ ] **Step 1: Write failing configuration tests**

```python
def test_default_profile_is_isolated_under_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = load_config()
    assert cfg.browser_profile_dir == tmp_path / "ASIATI" / "ResumeAgent" / "browser-profile"
    assert cfg.api_base_url == "https://dzcwl3yhv133t.cloudfront.net"


def test_api_base_url_is_https_and_has_no_trailing_slash(monkeypatch):
    monkeypatch.setenv("ASIATI_RESUME_AGENT_API_BASE_URL", "https://example.test/")
    assert load_config().api_base_url == "https://example.test"
```

Also reject non-HTTPS API base URLs except explicit `http://127.0.0.1`/`http://localhost` for local development tests.

- [ ] **Step 2: Write failing credential tests**

Monkeypatch `keyring.get_password`, `set_password` and `delete_password` and assert the service/username contract. `read_agent_token()` must reject an empty credential with a clear `AgentCredentialMissing` exception.

- [ ] **Step 3: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_config.py tools/indeed_resume_agent/tests/test_credential_store.py
```

Expected: package/modules do not exist.

- [ ] **Step 4: Implement config and keyring wrapper**

`setup_token.py` prompts without echo:

```python
from getpass import getpass

raw = getpass("Pegue el token del ASIATI Resume Agent: ").strip()
if len(raw) < 32:
    raise SystemExit("Token invalido: use la credencial emitida por el administrador.")
write_agent_token(raw)
print("Credencial guardada en Windows Credential Manager.")
```

Do not print the token.

- [ ] **Step 5: Create separate agent requirements**

`tools/indeed_resume_agent/requirements.txt` contains the agent-only dependencies:

```text
httpx==0.28.1
playwright>=1.50,<2
keyring>=25,<26
pyinstaller>=6,<7
```

Do not add Playwright or PyInstaller to the server `requirements.txt`.

- [ ] **Step 6: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_config.py tools/indeed_resume_agent/tests/test_credential_store.py
```

- [ ] **Step 7: Commit**

```bash
git add tools/indeed_resume_agent tools/__init__.py
git commit -m "feat: scaffold ASIATI resume agent"
```

---

### Task 2: Implement the least-privilege backend API client

**Files:**
- Create: `tools/indeed_resume_agent/api_client.py`
- Create: `tools/indeed_resume_agent/tests/test_api_client.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ClaimedTask:
    task_id: str
    candidate_name: str
    job_title: str
    resume_url: str
    lease_token: str
    lease_expires_at: datetime

@dataclass(frozen=True)
class QueueStats:
    pending: int
    claimed: int
    completed: int
    needs_human: int
    retry: int
    failed: int

class AgentApiClient:
    def claim(self) -> ClaimedTask | None: ...
    def heartbeat(self, task: ClaimedTask) -> datetime: ...
    def upload_resume(self, task: ClaimedTask, *, filename: str, data: bytes) -> dict: ...
    def needs_human(self, task: ClaimedTask, *, code: str) -> None: ...
    def fail(self, task: ClaimedTask, *, code: str) -> str: ...
    def resume_after_human(self, task_id: str) -> None: ...
    def stats(self) -> QueueStats: ...
```

- [ ] **Step 1: Write failing transport-contract tests**

Use `httpx.MockTransport` or inject `http_client`. Prove:
- every request includes `X-ASIATI-Agent-Token`;
- lease mutations include `X-ASIATI-Lease-Token`;
- `claim()` maps 204 to `None`;
- claim JSON parses timezone-aware `lease_expires_at`;
- upload sends multipart file with `application/pdf`;
- safe exceptions expose status/code but never echo response URLs, agent token or lease token;
- no client method calls general candidates/jobs endpoints.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_api_client.py
```

- [ ] **Step 3: Implement the API client**

Constructor:

```python
class AgentApiClient:
    def __init__(self, config: AgentConfig, token: str, *, http_client=None):
        self._config = config
        self._token = token
        self._http = http_client or httpx.Client(
            base_url=config.api_base_url,
            timeout=config.request_timeout_seconds,
            headers={"X-ASIATI-Agent-Token": token},
        )
```

For route errors, convert to a public local exception such as `AgentApiError(status_code, code)` without embedding raw backend response bodies.

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_api_client.py
```

- [ ] **Step 5: Commit**

```bash
git add tools/indeed_resume_agent/api_client.py tools/indeed_resume_agent/tests/test_api_client.py
git commit -m "feat: add resume agent API client"
```

---

### Task 3: Implement persistent visible Edge session and deterministic resume retrieval

**Files:**
- Create: `tools/indeed_resume_agent/browser.py`
- Create: `tools/indeed_resume_agent/tests/test_browser.py`

**Result contract:**

```python
class BrowserOutcome(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    NEEDS_HUMAN = "NEEDS_HUMAN"

@dataclass(frozen=True)
class BrowserResult:
    outcome: BrowserOutcome
    filename: str | None = None
    data: bytes | None = None
    human_code: str | None = None

class IndeedBrowser:
    def start(self) -> None: ...
    def close(self) -> None: ...
    def open_indeed(self) -> None: ...
    def fetch_resume(self, url: str) -> BrowserResult: ...
```

- [ ] **Step 1: Write failing profile/start tests**

Using a fake Playwright factory, assert:

```python
context = chromium.launch_persistent_context(
    user_data_dir=str(config.browser_profile_dir),
    channel="msedge",
    headless=False,
    accept_downloads=True,
)
```

The test must prove the dedicated path is used and no normal Chrome/Edge profile path is accepted or inferred.

- [ ] **Step 2: Write failing download-path tests**

Cover the supported deterministic paths in this order:
1. `context.request.get(resume_url)` returns status 200 and `Content-Type: application/pdf` -> use response body directly.
2. Otherwise open `resume_url` in visible page.
3. If URL/text indicates login, MFA, challenge or CAPTCHA -> `NEEDS_HUMAN`.
4. If a known download control (`Download`, `Descargar`, `Download CV`, `Descargar CV`, `Download resume`, `Descargar currículum`) triggers a Playwright `download` event -> read the file and return it.
5. If a page response supplies an application/pdf body during the deterministic flow -> return it.
6. Unknown page state -> `NEEDS_HUMAN` with `INDEED_UI_REQUIRES_REVIEW`; do not click arbitrary links.

- [ ] **Step 3: Write failing local PDF validation tests**

```python
def validate_pdf(data: bytes, *, max_bytes: int) -> None:
    if not data.startswith(b"%PDF-"):
        raise InvalidResumePdf("RESUME_NOT_PDF")
    if len(data) > max_bytes:
        raise InvalidResumePdf("RESUME_TOO_LARGE")
```

Also reject empty data. Filename normalization always ends in `.pdf` and removes path components.

- [ ] **Step 4: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_browser.py
```

- [ ] **Step 5: Implement browser lifecycle and retrieval**

Create profile directory before launch. Keep one persistent context for the process lifetime. Never call `context.clear_cookies()` during normal operation.

Challenge detection must be conservative and testable, using URL markers and visible text patterns such as `sign in`, `iniciar sesión`, `verification`, `verificación`, `captcha`, `security challenge`, without attempting to solve them.

- [ ] **Step 6: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_browser.py
```

- [ ] **Step 7: Commit**

```bash
git add tools/indeed_resume_agent/browser.py tools/indeed_resume_agent/tests/test_browser.py
git commit -m "feat: download Indeed resumes with persistent Edge"
```

---

### Task 4: Build the sequential worker state machine with heartbeat and crash-safe behavior

**Files:**
- Create: `tools/indeed_resume_agent/worker.py`
- Create: `tools/indeed_resume_agent/tests/test_worker.py`

**Worker interface:**

```python
@dataclass(frozen=True)
class WorkerSnapshot:
    state: str
    active_candidate: str | None
    processed_session: int
    last_error: str | None

class ResumeWorker:
    def run_once(self) -> WorkerSnapshot: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
```

- [ ] **Step 1: Write failing happy-path test**

Mock API + browser:

```text
claim task -> browser DOWNLOADED -> local validate -> upload -> next run sees empty queue
```

Assert exactly one upload and no `fail`/`needs_human` call.

- [ ] **Step 2: Write failing human-intervention test**

Browser returns `NEEDS_HUMAN`; worker calls backend `needs_human(task, code=...)`, does not upload, stops claiming new tasks while local state is `WAITING_FOR_HUMAN` until `resume_after_human(task_id)` succeeds.

- [ ] **Step 3: Write failing heartbeat test**

For a simulated long browser action, start a heartbeat helper thread/timer that calls `api.heartbeat(task)` every 120 seconds until the task finishes. In unit tests inject a fake scheduler/clock so the test is instantaneous.

Heartbeat failure must abort the active upload path because the worker can no longer prove it owns the lease.

- [ ] **Step 4: Write failing technical-failure test**

A browser/network technical exception calls `api.fail(task, code="RESUME_DOWNLOAD_FAILED")`. The backend decides whether the task becomes `RETRY` or `FAILED`; the local worker does not implement an independent retry counter.

- [ ] **Step 5: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_worker.py
```

- [ ] **Step 6: Implement the minimal worker**

`run_once()` logic:

```python
if paused_or_stopped:
    return snapshot

task = api.claim()
if task is None:
    return idle_snapshot

start_heartbeat(task)
try:
    result = browser.fetch_resume(task.resume_url)
    if result.outcome is BrowserOutcome.NEEDS_HUMAN:
        api.needs_human(task, code=result.human_code or "INDEED_HUMAN_REQUIRED")
        remember_human_task(task.task_id)
        return human_snapshot
    validate_pdf(result.data or b"", max_bytes=config.max_pdf_bytes)
    api.upload_resume(task, filename=result.filename or "indeed-resume.pdf", data=result.data or b"")
    return completed_snapshot
except LeaseLost:
    return lease_lost_snapshot
except Exception:
    api.fail(task, code="RESUME_DOWNLOAD_FAILED")
    return failed_snapshot
finally:
    stop_heartbeat()
```

Do not persist the task URL or lease token in local state.

- [ ] **Step 7: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_worker.py tools/indeed_resume_agent/tests/test_api_client.py tools/indeed_resume_agent/tests/test_browser.py
```

- [ ] **Step 8: Commit**

```bash
git add tools/indeed_resume_agent/worker.py tools/indeed_resume_agent/tests/test_worker.py
git commit -m "feat: add resume agent worker loop"
```

---

### Task 5: Add the minimal Tkinter operations UI

**Files:**
- Create: `tools/indeed_resume_agent/ui.py`
- Create: `tools/indeed_resume_agent/main.py`
- Create: `tools/indeed_resume_agent/tests/test_ui_state.py`

**UI requirements:**

```text
ASIATI Resume Agent

Indeed session: Ready / Needs attention

Pending:          N
Downloading:      0/1
Completed:        N
Needs attention:  N
Failed:           N

Current candidate: <name or ->
Status: <short safe text>

[Pause] [Resume] [Open Indeed]
```

No token, lease, resume URL, Gmail address or raw backend error body is shown.

- [ ] **Step 1: Write failing presentation-state tests**

Separate UI mapping from Tk widgets:

```python
@dataclass(frozen=True)
class UiState:
    session_label: str
    status_label: str
    pending: int
    downloading: int
    completed: int
    needs_attention: int
    failed: int
    current_candidate: str


def build_ui_state(snapshot: WorkerSnapshot, stats: QueueStats) -> UiState:
    ...
```

Tests prove state labels for idle, active, paused and needs-human conditions and that secret-looking fields do not exist.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_ui_state.py
```

- [ ] **Step 3: Implement Tkinter UI and background worker**

Run network/browser work on a daemon/background thread. Tk updates happen through `root.after(...)` on the main thread.

Buttons:
- `Pause` calls `worker.pause()` and does not terminate an already active deterministic download; it prevents the next claim.
- `Resume` calls `worker.resume()`; if a human task exists, call backend `resume_after_human(task_id)` before claiming again.
- `Open Indeed` calls `browser.open_indeed()` in the persistent visible context.

Poll stats periodically using `api.stats()` and sanitize operational errors to short local labels.

- [ ] **Step 4: Implement `main.py` composition root**

```python
def main() -> None:
    config = load_config()
    token = read_agent_token()
    api = AgentApiClient(config, token)
    browser = IndeedBrowser(config)
    browser.start()
    worker = ResumeWorker(config=config, api=api, browser=browser)
    run_ui(worker=worker, api=api, browser=browser)
```

Ensure `browser.close()` and `api.close()` run on normal exit.

- [ ] **Step 5: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_ui_state.py tools/indeed_resume_agent/tests/test_worker.py
```

- [ ] **Step 6: Commit**

```bash
git add tools/indeed_resume_agent/ui.py tools/indeed_resume_agent/main.py tools/indeed_resume_agent/tests/test_ui_state.py
git commit -m "feat: add ASIATI resume agent desktop UI"
```

---

### Task 6: Add local installation, packaging and first-run scripts

**Files:**
- Create: `tools/indeed_resume_agent/install.ps1`
- Create: `tools/indeed_resume_agent/run.ps1`
- Create: `tools/indeed_resume_agent/build.ps1`
- Create: `tools/indeed_resume_agent/README.md`
- Create: `tools/indeed_resume_agent/tests/test_packaging_contract.py`

- [ ] **Step 1: Write failing packaging-contract tests**

Assert the scripts exist and protect these rules:
- `install.ps1` creates a local venv and installs only `tools/indeed_resume_agent/requirements.txt`;
- it never embeds an agent token;
- `run.ps1` launches `python -m tools.indeed_resume_agent.main` from the repo/installation root;
- `build.ps1` packages as a directory (`--onedir`), not a fragile single-file executable;
- PyInstaller includes Playwright package data and uses the installed Edge channel at runtime;
- no `playwright install chromium` command is required for the MVP because the target machine uses installed Microsoft Edge.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tools/indeed_resume_agent/tests/test_packaging_contract.py
```

- [ ] **Step 3: Implement PowerShell scripts**

`install.ps1` outline:

```powershell
$ErrorActionPreference = "Stop"
python -m venv .agent-venv
& .\.agent-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.agent-venv\Scripts\pip.exe install -r .\tools\indeed_resume_agent\requirements.txt
& .\.agent-venv\Scripts\python.exe -m tools.indeed_resume_agent.setup_token
```

`build.ps1` uses:

```powershell
& .\.agent-venv\Scripts\pyinstaller.exe `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --collect-all playwright `
  --name "ASIATI Resume Agent" `
  .\tools\indeed_resume_agent\main.py
```

If packaging tests on Windows show Playwright requires additional data collection, add it explicitly to the generated `.spec`; do not switch to `--onefile` merely to hide the issue.

- [ ] **Step 4: Document first run**

README sequence:
1. verify Microsoft Edge is installed;
2. run `install.ps1` as the Katherine Windows user;
3. enter the machine token into the hidden prompt;
4. run `run.ps1`;
5. click `Open Indeed`;
6. Katherine signs in manually in the dedicated agent browser if required;
7. keep the browser profile local;
8. run one real task before enabling a batch.

Document credential removal command using `python -c`/the credential wrapper rather than deleting browser data.

- [ ] **Step 5: Verify GREEN**

```bash
pytest -q tools/indeed_resume_agent/tests/test_packaging_contract.py
```

On Windows, additionally run:

```powershell
.\tools\indeed_resume_agent\build.ps1
```

Expected: `dist\ASIATI Resume Agent\` is created and launches without missing Playwright driver/package errors.

- [ ] **Step 6: Commit**

```bash
git add tools/indeed_resume_agent/install.ps1 tools/indeed_resume_agent/run.ps1 tools/indeed_resume_agent/build.ps1 tools/indeed_resume_agent/README.md tools/indeed_resume_agent/tests/test_packaging_contract.py
git commit -m "feat: package ASIATI resume agent for Windows"
```

---

### Task 7: Full agent verification with mocked CI and controlled Windows smoke test

- [ ] **Step 1: Run all agent unit tests**

```bash
pytest -q tools/indeed_resume_agent/tests
```

Expected: all green and no network call to Indeed/AWS.

- [ ] **Step 2: Run server contract tests required by the agent**

```bash
pytest -q \
  app/tests/test_indeed_agent_auth.py \
  app/tests/test_indeed_agent_routes.py \
  app/tests/test_indeed_agent_upload.py \
  app/tests/test_indeed_email_resume_leases.py
```

Expected: all green.

- [ ] **Step 3: Secret scan**

```bash
git grep -nE "(X-ASIATI-Agent-Token: [A-Za-z0-9_-]{20,}|agent-token=|INDEED_PASSWORD|password.*indeed)" -- tools app docs
```

Expected: no real credential/password values. Documentation/header names without values are acceptable after manual review.

- [ ] **Step 4: Controlled Windows smoke test with one real application**

This is deliberately manual and not CI:
1. backend is already deployed with machine API enabled;
2. agent token is in Windows Credential Manager;
3. Gmail sync creates exactly one `WAITING_DOWNLOAD` task;
4. start agent;
5. if Indeed asks for login/MFA/CAPTCHA, Katherine completes it manually;
6. agent downloads one PDF and uploads it;
7. backend task becomes `COMPLETED`;
8. source `CandidateIngestionEvent` becomes `STORED`, then the existing worker processes it;
9. verify candidate appears in the existing application and is associated to the intended job or `JOB_UNRESOLVED` when ambiguity is intentional.

- [ ] **Step 5: Controlled batch of 5-10**

Measure per-task duration, session stability, count of `NEEDS_HUMAN`, retries and failures. Do not increase browser concurrency.

- [ ] **Step 6: Release the backlog only after small-batch stability**

For a backlog around 200 applications, keep a single agent/browser worker. If the workstation stops, rely on server lease expiry/reclaim; do not reset completed tasks.

- [ ] **Step 7: Record smoke/batch results in the operations doc**

Append only non-sensitive counts/timings and any deterministic UI selector adjustments to `docs/indeed-resume-agent-operations.md`. Do not paste candidate CV content, resume URLs, tokens or cookies.

---

## Integration Gate

The Windows agent is considered ready for production only when both this plan and `2026-09-17-indeed-email-resume-backend.md` are green. Production cutover then follows the operations runbook in this order:

```text
backend deployed/migrated
-> agent machine secret configured
-> raw token stored in Katherine Windows Credential Manager
-> agent authenticates and stats endpoint works
-> Gmail query changed to from:indeedemail.com and enabled
-> one real application smoke test
-> 5-10 application batch
-> larger backlog
```

Rollback is safe: disable Gmail ingestion and stop the local agent. Already completed candidate-ingestion events remain durable and are not deleted.