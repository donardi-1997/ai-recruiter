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
class FullSyncResult:
    pages: int
    discovered: int
    created: int
    existing: int
    needs_review: int
    skipped: int
    reconcile_jobs: int
    reconcile_scanned: int
    reconcile_ready: int
    reconcile_provider_pending: int
    reconcile_covered: int
    reconcile_queued: int


@dataclass(frozen=True)
class VacancySyncResult:
    discovered: int
    created: int
    updated: int
    reconciled: int
    unchanged: int
    missing_identity: int
    missing_description: int
    ambiguous: int
    descriptions_recovered: int
    applications_recovered: int = 0


@dataclass(frozen=True)
class QueueStats:
    pending: int
    claimed: int
    completed: int
    needs_human: int
    retry: int
    failed: int
    last_error_code: str | None = None
    last_error_candidate: str | None = None
    last_error_status: str | None = None


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

    def upload_resume(
        self,
        task: ClaimedTask,
        *,
        filename: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> dict:
        response = self._request(
            "POST",
            f"{BASE_PATH}/{task.task_id}/resume",
            lease_token=task.lease_token,
            files={"file": (filename, data, str(content_type))},
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

    def retry_failed(self) -> int:
        response = self._request("POST", f"{BASE_PATH}/retry-failed")
        return int(response.json().get("requeued", 0))

    def retry_attention(self) -> int:
        response = self._request("POST", f"{BASE_PATH}/retry-attention")
        return int(response.json().get("requeued", 0))

    def sync_jobs(self, snapshots: list[dict]) -> VacancySyncResult:
        payload = dict(
            self._request(
                "POST",
                f"{BASE_PATH}/jobs/sync",
                json={"snapshots": list(snapshots or [])},
            ).json()
        )
        return VacancySyncResult(
            discovered=int(payload.get("discovered") or 0),
            created=int(payload.get("created") or 0),
            updated=int(payload.get("updated") or 0),
            reconciled=int(payload.get("reconciled") or 0),
            unchanged=int(payload.get("unchanged") or 0),
            missing_identity=int(payload.get("missing_identity") or 0),
            missing_description=int(payload.get("missing_description") or 0),
            ambiguous=int(payload.get("ambiguous") or 0),
            descriptions_recovered=int(payload.get("descriptions_recovered") or 0),
            applications_recovered=int(payload.get("applications_recovered") or 0),
        )

    def sync_all(self, *, max_pages: int = 200) -> FullSyncResult:
        """Exhaust bounded historical discovery, then perform one incremental catch-up."""
        limit = max(1, min(int(max_pages), 500))
        totals = {
            "discovered": 0,
            "created": 0,
            "existing": 0,
            "needs_review": 0,
            "skipped": 0,
            "reconcile_queued": 0,
        }
        latest = {
            "reconcile_jobs": 0,
            "reconcile_scanned": 0,
            "reconcile_ready": 0,
            "reconcile_provider_pending": 0,
            "reconcile_covered": 0,
        }
        pages = 0
        catchup_required = False

        while pages < limit:
            payload = dict(self._request("POST", f"{BASE_PATH}/sync").json())
            pages += 1
            for key in totals:
                totals[key] += int(payload.get(key) or 0)
            for key in latest:
                latest[key] = int(payload.get(key) or 0)

            mode = str(payload.get("mode") or "")
            has_more = bool(payload.get("has_more"))
            if has_more:
                continue

            if mode in {"FULL", "FULL_CONTINUE", "FULL_RECOVERY"} and not catchup_required:
                catchup_required = True
                continue
            break
        else:
            raise AgentApiError(409, "RESUME_SYNC_PAGE_LIMIT")

        return FullSyncResult(
            pages=pages,
            discovered=totals["discovered"],
            created=totals["created"],
            existing=totals["existing"],
            needs_review=totals["needs_review"],
            skipped=totals["skipped"],
            reconcile_jobs=latest["reconcile_jobs"],
            reconcile_scanned=latest["reconcile_scanned"],
            reconcile_ready=latest["reconcile_ready"],
            reconcile_provider_pending=latest["reconcile_provider_pending"],
            reconcile_covered=latest["reconcile_covered"],
            reconcile_queued=totals["reconcile_queued"],
        )

    def stats(self) -> QueueStats:
        payload = self._request("GET", f"{BASE_PATH}/stats").json()
        return QueueStats(
            pending=int(payload.get("pending", 0)),
            claimed=int(payload.get("claimed", 0)),
            completed=int(payload.get("completed", 0)),
            needs_human=int(payload.get("needs_human", 0)),
            retry=int(payload.get("retry", 0)),
            failed=int(payload.get("failed", 0)),
            last_error_code=(
                str(payload.get("last_error_code"))
                if payload.get("last_error_code")
                else None
            ),
            last_error_candidate=(
                str(payload.get("last_error_candidate"))
                if payload.get("last_error_candidate")
                else None
            ),
            last_error_status=(
                str(payload.get("last_error_status"))
                if payload.get("last_error_status")
                else None
            ),
        )