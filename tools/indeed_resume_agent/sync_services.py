from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .api_client import FullSyncResult, QueueStats, VacancySyncResult
from .vacancy_sync import collect_vacancy_snapshots


@dataclass(frozen=True)
class VacancySyncReport:
    result: VacancySyncResult
    stats: QueueStats
    expected_total: int
    discovered: int
    hydrated: int
    detail_failures: int
    descriptions_extracted: int
    warning_code: str | None = None


@dataclass(frozen=True)
class CandidateSyncReport:
    result: FullSyncResult
    stats: QueueStats


@dataclass(frozen=True)
class FullSyncReport:
    vacancy_report: VacancySyncReport | None
    candidate_report: CandidateSyncReport
    vacancy_error: str | None = None


class VacancySyncService:
    """Refresh Indeed vacancies without touching candidate discovery or CV work."""

    def __init__(
        self,
        *,
        api,
        browser,
        collector: Callable[[object], list[dict]] = collect_vacancy_snapshots,
    ) -> None:
        self._api = api
        self._browser = browser
        self._collector = collector

    def run(self) -> VacancySyncReport:
        snapshots = list(self._collector(self._browser) or [])
        diagnostics = dict(
            getattr(self._browser, "_last_job_sync_diagnostics", None) or {}
        )

        descriptions_extracted = int(
            diagnostics.get("descriptions_extracted")
            or sum(1 for row in snapshots if str(row.get("description") or "").strip())
        )
        discovered = int(diagnostics.get("discovered") or len(snapshots))
        hydrated = int(diagnostics.get("hydrated") or len(snapshots))
        expected_total = int(diagnostics.get("expected_total") or discovered)
        detail_failures = int(diagnostics.get("detail_failures") or 0)
        list_incomplete = bool(diagnostics.get("list_incomplete"))

        result = self._api.sync_jobs(snapshots)
        stats = self._api.stats()

        warning_code = None
        if (
            list_incomplete
            or detail_failures > 0
            or (expected_total > 0 and discovered < expected_total)
            or hydrated < discovered
        ):
            warning_code = "INDEED_JOB_SYNC_PARTIAL"

        return VacancySyncReport(
            result=result,
            stats=stats,
            expected_total=expected_total,
            discovered=discovered,
            hydrated=hydrated,
            detail_failures=detail_failures,
            descriptions_extracted=descriptions_extracted,
            warning_code=warning_code,
        )


class CandidateSyncService:
    """Run incremental application/candidate discovery without crawling vacancies."""

    def __init__(self, *, api) -> None:
        self._api = api

    def run(self) -> CandidateSyncReport:
        result = self._api.sync_all()
        stats = self._api.stats()
        return CandidateSyncReport(result=result, stats=stats)


class SyncCoordinator:
    """Compose independent sync operations without making candidates depend on jobs.

    Vacancy authentication is a global browser blocker and stops the combined
    operation. Other vacancy failures are preserved as a safe code while the
    incremental candidate/application sync proceeds against the catalog that is
    already known by the backend.
    """

    def __init__(self, *, vacancy_service, candidate_service) -> None:
        self._vacancy_service = vacancy_service
        self._candidate_service = candidate_service

    def run_all(self) -> FullSyncReport:
        vacancy_report = None
        vacancy_error = None
        try:
            vacancy_report = self._vacancy_service.run()
        except RuntimeError as exc:
            vacancy_error = str(exc).strip() or "INDEED_JOB_SYNC_FAILED"
            if vacancy_error == "INDEED_AUTH_REQUIRED":
                raise
        except Exception:
            vacancy_error = "INDEED_JOB_SYNC_FAILED"

        candidate_report = self._candidate_service.run()
        return FullSyncReport(
            vacancy_report=vacancy_report,
            candidate_report=candidate_report,
            vacancy_error=vacancy_error,
        )
