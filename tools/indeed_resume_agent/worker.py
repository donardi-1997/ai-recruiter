from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from .api_client import AgentApiError, LeaseLost
from .browser import (
    BrowserFetchStageError,
    BrowserOutcome,
    InvalidResumeDocument,
    PDF_CONTENT_TYPE,
    validate_resume_document,
)
from .config import AgentConfig

GLOBAL_HUMAN_BLOCKING_CODES = {"INDEED_AUTH_REQUIRED"}
_SAFE_SYMBOLIC_BROWSER_ERROR = re.compile(
    r"^(?:INDEED|BROWSER_USE|RESUME)_[A-Z0-9_]{2,100}$"
)


def _safe_browser_failure_code(exc: Exception) -> str:
    """Classify unexpected browser failures without exposing exception details."""
    if isinstance(exc, TimeoutError):
        return "RESUME_BROWSER_TIMEOUT"
    if isinstance(exc, PermissionError):
        return "RESUME_BROWSER_PERMISSION_DENIED"
    if isinstance(exc, FileNotFoundError):
        return "RESUME_BROWSER_FILE_NOT_FOUND"
    if isinstance(exc, ConnectionError):
        return "RESUME_BROWSER_CONNECTION_ERROR"
    if isinstance(exc, OSError):
        return "RESUME_BROWSER_OS_ERROR"

    raw = str(exc or "").strip().upper()
    if not _SAFE_SYMBOLIC_BROWSER_ERROR.fullmatch(raw):
        return "RESUME_BROWSER_FETCH_FAILED"
    if raw.startswith("RESUME_BROWSER_"):
        return raw[:120]
    if raw.startswith("RESUME_"):
        return raw[:120]
    if raw.startswith("BROWSER_USE_"):
        return f"RESUME_{raw}"[:120]
    return f"RESUME_BROWSER_{raw}"[:120]


@dataclass(frozen=True)
class WorkerSnapshot:
    state: str
    active_candidate: str | None
    processed_session: int
    last_error: str | None


class HeartbeatLoop:
    def __init__(self, *, api, task, interval_seconds: float):
        self._api = api
        self._task = task
        self._interval = float(interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: Exception | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="asiati-resume-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._api.heartbeat(self._task)
            except Exception as exc:
                self.error = exc
                self._stop.set()
                return

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)


class ResumeWorker:
    def __init__(
        self,
        *,
        config: AgentConfig,
        api,
        browser,
        heartbeat_factory=None,
        start_paused: bool = False,
    ):
        self._config = config
        self._api = api
        self._browser = browser
        self._heartbeat_factory = heartbeat_factory or (
            lambda **kw: HeartbeatLoop(**kw)
        )
        self._paused = bool(start_paused)
        self._stopped = False
        self._human_task_id: str | None = None
        self._human_resume_url: str | None = None
        self._processed_session = 0
        self._last_snapshot = WorkerSnapshot(
            "PAUSED" if self._paused else "IDLE",
            None,
            0,
            None,
        )

    @property
    def snapshot(self) -> WorkerSnapshot:
        return self._last_snapshot

    @property
    def human_task_id(self) -> str | None:
        return self._human_task_id

    @property
    def human_resume_url(self) -> str | None:
        return self._human_resume_url

    def _set(self, state: str, *, candidate: str | None = None, error: str | None = None) -> WorkerSnapshot:
        self._last_snapshot = WorkerSnapshot(
            state=state,
            active_candidate=candidate,
            processed_session=self._processed_session,
            last_error=error,
        )
        return self._last_snapshot

    def pause(self) -> None:
        self._paused = True
        if self._human_task_id is None:
            self._set("PAUSED")

    def resume(self) -> None:
        if self._human_task_id is not None:
            task_id = self._human_task_id
            self._api.resume_after_human(task_id)
            self._human_task_id = None
            self._human_resume_url = None
        self._paused = False
        if not self._stopped:
            self._set("IDLE")

    def reset_after_attention_retry(self) -> None:
        """Clear local human-intervention state after an owner-scoped backend requeue."""
        self._human_task_id = None
        self._human_resume_url = None
        self._paused = False
        if not self._stopped:
            self._set("IDLE")

    def stop(self) -> None:
        self._stopped = True
        self._set("STOPPED")

    def run_once(self) -> WorkerSnapshot:
        if self._stopped:
            return self._set("STOPPED")
        if self._human_task_id is not None:
            return self._set("WAITING_FOR_HUMAN")
        if self._paused:
            return self._set("PAUSED")

        try:
            task = self._api.claim()
        except AgentApiError as exc:
            return self._set(
                "ERROR",
                error=f"CLAIM_{exc.code}"[:120],
            )
        except Exception:
            return self._set(
                "ERROR",
                error="CLAIM_REQUEST_FAILED",
            )
        if task is None:
            return self._set("IDLE")

        heartbeat = self._heartbeat_factory(
            api=self._api,
            task=task,
            interval_seconds=self._config.heartbeat_interval_seconds,
        )
        self._set("DOWNLOADING", candidate=task.candidate_name)
        heartbeat.start()
        stage = "BROWSER_FETCH"
        try:
            result = self._browser.fetch_resume(
                task.resume_url,
                candidate_name=task.candidate_name,
                job_title=task.job_title,
            )

            if heartbeat.error is not None:
                return self._set(
                    "LEASE_LOST",
                    candidate=task.candidate_name,
                    error="No se pudo confirmar la vigencia de la tarea.",
                )

            if result.outcome is BrowserOutcome.NEEDS_HUMAN:
                code = result.human_code or "INDEED_HUMAN_REQUIRED"
                self._api.needs_human(task, code=code)
                detail = code
                if result.diagnostic_path:
                    detail = f"{code} — Diagnóstico local: {result.diagnostic_path}"

                if code in GLOBAL_HUMAN_BLOCKING_CODES:
                    self._human_task_id = task.task_id
                    self._human_resume_url = task.resume_url
                    return self._set(
                        "WAITING_FOR_HUMAN",
                        candidate=task.candidate_name,
                        error=detail,
                    )

                return self._set(
                    "NEEDS_REVIEW_CONTINUE",
                    candidate=task.candidate_name,
                    error=detail,
                )

            stage = "DOCUMENT_VALIDATE"
            data = result.data or b""
            content_type = validate_resume_document(
                data,
                filename=result.filename,
                content_type=result.content_type,
                max_bytes=self._config.max_pdf_bytes,
            )

            if heartbeat.error is not None:
                return self._set(
                    "LEASE_LOST",
                    candidate=task.candidate_name,
                    error="No se pudo confirmar la vigencia de la tarea.",
                )

            stage = "UPLOAD"
            self._api.upload_resume(
                task,
                filename=result.filename or (
                    "indeed-resume.pdf"
                    if content_type == PDF_CONTENT_TYPE
                    else "indeed-resume.docx"
                ),
                data=data,
                content_type=content_type,
            )
            self._processed_session += 1
            return self._set("COMPLETED", candidate=task.candidate_name)
        except LeaseLost:
            return self._set(
                "LEASE_LOST",
                candidate=task.candidate_name,
                error="La tarea perdió su lease y será reclamada de forma segura.",
            )
        except BrowserFetchStageError as exc:
            status = self._api.fail(task, code=exc.code)
            try:
                reset = getattr(self._browser, "reset_session", None)
                if callable(reset):
                    reset()
            except Exception:
                pass
            return self._set(
                status,
                candidate=task.candidate_name,
                error=exc.code,
            )
        except InvalidResumeDocument as exc:
            status = self._api.fail(task, code=exc.code)
            return self._set(
                status,
                candidate=task.candidate_name,
                error=exc.code,
            )
        except AgentApiError as exc:
            safe_code = f"RESUME_{stage}_{exc.code}"[:120]
            try:
                status = self._api.fail(task, code=safe_code)
            except LeaseLost:
                return self._set(
                    "LEASE_LOST",
                    candidate=task.candidate_name,
                    error="RESUME_TASK_LEASE_LOST",
                )
            return self._set(
                status,
                candidate=task.candidate_name,
                error=safe_code,
            )
        except Exception as exc:
            safe_code = (
                _safe_browser_failure_code(exc)
                if stage == "BROWSER_FETCH"
                else {
                    "DOCUMENT_VALIDATE": "RESUME_DOCUMENT_VALIDATE_FAILED",
                    "UPLOAD": "RESUME_UPLOAD_FAILED",
                }.get(stage, "RESUME_DOWNLOAD_FAILED")
            )
            if stage == "BROWSER_FETCH":
                try:
                    reset = getattr(self._browser, "reset_session", None)
                    if callable(reset):
                        reset()
                except Exception:
                    pass
            try:
                status = self._api.fail(task, code=safe_code)
            except LeaseLost:
                return self._set(
                    "LEASE_LOST",
                    candidate=task.candidate_name,
                    error="RESUME_TASK_LEASE_LOST",
                )
            return self._set(
                status,
                candidate=task.candidate_name,
                error=safe_code,
            )
        finally:
            heartbeat.stop()
