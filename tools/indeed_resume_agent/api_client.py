from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import AgentConfig

BASE_PATH = "/api/agents/indeed-resume"
_SAFE_CODE = re.compile(r"^[A-Z0-9_]{3,120}$")


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


class AgentApiError(RuntimeError):
    def __init__(self, status_code: int, code: str):
        self.status_code = int(status_code)
        self.code = str(code)
        super().__init__(f"ASIATI Resume Agent API error {self.status_code}: {self.code}")


class LeaseLost(AgentApiError):
    pass


def _parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class AgentApiClient:
    def __init__(self, config: AgentConfig, token: str, *, http_client=None):
        self._config = config
        self._token = str(token)
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=config.api_base_url,
            timeout=config.request_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _safe_error(self, response: httpx.Response) -> AgentApiError:
        detail = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail")
        except Exception:
            detail = None
        candidate = str(detail or "").strip()
        code = candidate if _SAFE_CODE.fullmatch(candidate) else f"HTTP_{response.status_code}"
        error_type = LeaseLost if response.status_code == 409 and code.startswith("RESUME_TASK_LEASE_") else AgentApiError
        return error_type(response.status_code, code)

    def _request(self, method: str, path: str, *, lease_token: str | None = None, **kwargs) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-ASIATI-Agent-Token"] = self._token
        if lease_token:
            headers["X-ASIATI-Lease-Token"] = lease_token
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise self._safe_error(response)
        return response

    def _parse_claim(self, payload: dict) -> ClaimedTask:
        return ClaimedTask(
            task_id=str(payload["task_id"]),
            candidate_name=str(payload.get("candidate_name") or ""),
            job_title=str(payload.get("job_title") or ""),
            resume_url=str(payload["resume_url"]),
            lease_token=str(payload["lease_token"]),
            lease_expires_at=_parse_datetime(payload["lease_expires_at"]),
        )

    def claim(self) -> ClaimedTask | None:
        response = self._request("POST", f"{BASE_PATH}/claim")
        if response.status_code == 204:
            return None
        return self._parse_claim(response.json())

    def heartbeat(self, task: ClaimedTask) -> datetime:
        response = self._request(
            "POST",
            f"{BASE_PATH}/{task.task_id}/heartbeat",
            lease_token=task.lease_token,
        )
        return _parse_datetime(response.json()["lease_expires_at"])

    def upload_resume(self, task: ClaimedTask, *, filename: str, data: bytes) -> dict:
        response = self._request(
            "POST",
            f"{BASE_PATH}/{task.task_id}/resume",
            lease_token=task.lease_token,
            files={"file": (filename, data, "application/pdf")},
        )
        return dict(response.json())

    def needs_human(self, task: ClaimedTask, *, code: str) -> None:
        self._request(
            "POST",
            f"{BASE_PATH}/{task.task_id}/needs-human",
            lease_token=task.lease_token,
            json={"code": str(code)},
        )

    def fail(self, task: ClaimedTask, *, code: str) -> str:
        response = self._request(
            "POST",
            f"{BASE_PATH}/{task.task_id}/fail",
            lease_token=task.lease_token,
            json={"code": str(code)},
        )
        return str(response.json().get("status") or "FAILED")

    def resume_after_human(self, task_id: str) -> None:
        self._request("POST", f"{BASE_PATH}/{task_id}/resume-after-human")

    def stats(self) -> QueueStats:
        payload = self._request("GET", f"{BASE_PATH}/stats").json()
        return QueueStats(
            pending=int(payload.get("pending", 0)),
            claimed=int(payload.get("claimed", 0)),
            completed=int(payload.get("completed", 0)),
            needs_human=int(payload.get("needs_human", 0)),
            retry=int(payload.get("retry", 0)),
            failed=int(payload.get("failed", 0)),
        )
