from tools.indeed_resume_agent.api_client import QueueStats
from tools.indeed_resume_agent.ui_v2 import build_ui_state
from tools.indeed_resume_agent.worker import WorkerSnapshot


def stats():
    return QueueStats(
        pending=4,
        claimed=0,
        completed=10,
        needs_human=1,
        retry=0,
        failed=0,
    )


def snap(state, detail=None):
    return WorkerSnapshot(state, None, 0, detail)


def test_vacancy_refresh_states_are_explicit():
    syncing = build_ui_state(snap("SYNCING_JOBS"), stats())
    completed = build_ui_state(
        snap(
            "JOBS_SYNC_COMPLETED",
            "Vacantes: 47 encontradas · 2 creadas · 3 actualizadas · 42 sin cambios · 4 descripciones recuperadas",
        ),
        stats(),
    )

    assert syncing.status_label == "Actualizando vacantes y descripciones desde Indeed..."
    assert completed.status_label.startswith("Vacantes: 47 encontradas")
    assert "4 descripciones recuperadas" in completed.status_label
    assert syncing.busy is True


def test_application_sync_phase_is_not_described_as_full_historical_review():
    syncing = build_ui_state(snap("SYNCING_APPLICATIONS"), stats())
    assert syncing.status_label == "Buscando postulaciones nuevas desde el último cursor..."
    assert "todas" not in syncing.status_label.casefold()
    assert syncing.busy is True
