from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.indeed_resume_agent.api_client import FullSyncResult, QueueStats, VacancySyncResult
from tools.indeed_resume_agent.sync_services import (
    CandidateSyncService,
    SyncCoordinator,
    VacancySyncService,
)


@dataclass
class FakeBrowser:
    _last_job_sync_diagnostics: dict | None = None


class FakeApi:
    def __init__(self):
        self.synced_snapshots = None
        self.sync_all_calls = 0

    def sync_jobs(self, snapshots):
        self.synced_snapshots = list(snapshots)
        return VacancySyncResult(
            discovered=len(self.synced_snapshots),
            created=len(self.synced_snapshots),
            updated=0,
            reconciled=0,
            unchanged=0,
            missing_identity=0,
            missing_description=0,
            ambiguous=0,
            descriptions_recovered=len(self.synced_snapshots),
        )

    def sync_all(self):
        self.sync_all_calls += 1
        return FullSyncResult(
            pages=1,
            discovered=1,
            created=1,
            existing=0,
            needs_review=0,
            skipped=0,
            reconcile_jobs=0,
            reconcile_scanned=0,
            reconcile_ready=0,
            reconcile_provider_pending=0,
            reconcile_covered=0,
            reconcile_queued=1,
        )

    def stats(self):
        return QueueStats(1, 0, 10, 0, 0, 0)


def test_vacancy_service_syncs_hydrated_rows_even_when_listing_is_partial():
    api = FakeApi()
    browser = FakeBrowser()
    snapshots = [
        {
            "external_job_key": "job-1",
            "title": "Vacante uno",
            "description": "Descripción completa de la vacante uno.",
        },
        {
            "external_job_key": "job-2",
            "title": "Vacante dos",
            "description": "Descripción completa de la vacante dos.",
        },
    ]

    def collector(_browser):
        _browser._last_job_sync_diagnostics = {
            "expected_total": 407,
            "discovered": 406,
            "hydrated": 2,
            "detail_failures": 404,
        }
        return snapshots

    report = VacancySyncService(api=api, browser=browser, collector=collector).run()

    assert api.synced_snapshots == snapshots
    assert report.result.created == 2
    assert report.expected_total == 407
    assert report.discovered == 406
    assert report.hydrated == 2
    assert report.detail_failures == 404
    assert report.warning_code == "INDEED_JOB_SYNC_PARTIAL"


def test_candidate_service_is_independent_from_vacancy_browser_logic():
    api = FakeApi()
    candidate_service = CandidateSyncService(api=api)

    report = candidate_service.run()

    assert api.sync_all_calls == 1
    assert report.result.created == 1
    assert report.stats.pending == 1


def test_full_sync_continues_candidates_when_vacancy_refresh_has_non_auth_failure():
    api = FakeApi()

    class BrokenVacancies:
        def run(self):
            raise RuntimeError("INDEED_JOB_LIST_INCOMPLETE")

    coordinator = SyncCoordinator(
        vacancy_service=BrokenVacancies(),
        candidate_service=CandidateSyncService(api=api),
    )

    report = coordinator.run_all()

    assert report.vacancy_report is None
    assert report.vacancy_error == "INDEED_JOB_LIST_INCOMPLETE"
    assert report.candidate_report.result.created == 1
    assert api.sync_all_calls == 1


def test_full_sync_stops_on_auth_failure_before_candidate_sync():
    api = FakeApi()

    class AuthBlockedVacancies:
        def run(self):
            raise RuntimeError("INDEED_AUTH_REQUIRED")

    coordinator = SyncCoordinator(
        vacancy_service=AuthBlockedVacancies(),
        candidate_service=CandidateSyncService(api=api),
    )

    with pytest.raises(RuntimeError, match="INDEED_AUTH_REQUIRED"):
        coordinator.run_all()

    assert api.sync_all_calls == 0
