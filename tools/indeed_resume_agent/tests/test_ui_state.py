from tools.indeed_resume_agent.api_client import QueueStats
from tools.indeed_resume_agent.ui import UiState, build_ui_state
from tools.indeed_resume_agent.worker import WorkerSnapshot


def stats(**overrides):
    values={"pending":4,"claimed":0,"completed":10,"needs_human":1,"retry":2,"failed":3}
    values.update(overrides)
    return QueueStats(**values)


def snap(state, candidate=None, error=None, processed=0):
    return WorkerSnapshot(state, candidate, processed, error)


def test_idle_ui_state_is_safe_and_operational():
    ui=build_ui_state(snap("IDLE"), stats())
    assert ui.session_label == "Ready"
    assert ui.status_label == "Esperando tareas"
    assert ui.pending == 4 and ui.completed == 10 and ui.downloading == 0
    assert ui.retry == 2
    assert ui.current_candidate == "-"


def test_idle_ui_surfaces_latest_safe_failure_code():
    ui=build_ui_state(
        snap("IDLE"),
        stats(
            pending=0,
            retry=0,
            failed=2,
            last_error_code="RESUME_UPLOAD_FAILED",
            last_error_candidate="Alejandra",
            last_error_status="FAILED",
        ),
    )
    assert ui.status_label == "Último error: RESUME_UPLOAD_FAILED — Alejandra"


def test_retry_state_surfaces_worker_stage_code():
    ui=build_ui_state(
        snap("RETRY", "Alejandra", "RESUME_BROWSER_FETCH_FAILED"),
        stats(retry=1, failed=0),
    )
    assert ui.status_label == "RESUME_BROWSER_FETCH_FAILED"


def test_active_and_paused_labels():
    active=build_ui_state(snap("DOWNLOADING","Ada"), stats(claimed=1))
    paused=build_ui_state(snap("PAUSED"), stats())
    assert active.downloading == 1 and active.current_candidate == "Ada"
    assert active.status_label == "Descargando CV..."
    assert paused.status_label == "En pausa"


def test_browser_ready_keeps_same_chrome_open_for_manual_login():
    ui=build_ui_state(snap("BROWSER_READY"), stats())
    assert "Chrome está abierto" in ui.status_label
    assert "mantén Chrome abierto" in ui.status_label
    assert "pulsa Resume" in ui.status_label
    assert "cierra chrome" not in ui.status_label.casefold()
    assert ui.session_label == "Ready"


def test_manual_login_required_has_explicit_instruction():
    ui=build_ui_state(snap("MANUAL_LOGIN_REQUIRED"), stats())
    assert "Open Indeed (Google Chrome)" in ui.status_label
    assert "inicia sesión" in ui.status_label
    assert "pulsa Resume" in ui.status_label


def test_diagnostic_anchor_failure_is_explicit():
    ui=build_ui_state(snap("DIAGNOSTIC_ANCHOR_FAILED"), stats())
    assert "pestaña de respaldo" in ui.status_label
    assert "Diagnostic mode" in ui.status_label


def test_diagnostic_mode_and_saved_path_are_explicit():
    active=build_ui_state(snap("DIAGNOSTIC_MODE","Ada"), stats())
    saved=build_ui_state(
        snap(
            "DIAGNOSTIC_SAVED",
            "Ada",
            r"Diagnóstico guardado: C:\Users\test\AppData\Local\ASIATI\ResumeAgent\diagnostics\indeed-flow-diagnostic.json",
        ),
        stats(),
    )
    assert "Modo diagnóstico activo" in active.status_label
    assert "indeed-flow-diagnostic.json" in saved.status_label


def test_needs_human_is_attention_state():
    ui=build_ui_state(snap("WAITING_FOR_HUMAN","Ada","internal error should not leak"), stats(needs_human=2))
    assert ui.session_label == "Needs attention"
    assert ui.status_label == "Indeed requiere intervención manual"
    assert ui.needs_attention == 2
    assert "internal" not in ui.status_label


def test_needs_human_surfaces_only_safe_error_code():
    ui=build_ui_state(
        snap("WAITING_FOR_HUMAN","Ada","INDEED_AUTH_REQUIRED"),
        stats(needs_human=1),
    )
    assert ui.status_label == "INDEED_AUTH_REQUIRED"

    unsafe=build_ui_state(
        snap("WAITING_FOR_HUMAN","Ada","internal error with secret URL"),
        stats(needs_human=1),
    )
    assert unsafe.status_label == "Indeed requiere intervención manual"


def test_ui_state_has_no_secret_fields():
    fields=set(UiState.__dataclass_fields__)
    forbidden={"token","lease_token","resume_url","gmail_address","raw_error"}
    assert fields.isdisjoint(forbidden)


def test_full_sync_states_are_explicit_and_attention_safe():
    syncing = build_ui_state(snap("SYNCING"), stats())
    completed = build_ui_state(
        snap("FULL_SYNC_COMPLETED", error="Prueba final completada: cola en cero."),
        stats(pending=0, retry=0, failed=0, needs_human=0),
    )
    attention = build_ui_state(
        snap(
            "FULL_SYNC_ATTENTION",
            error="Revisión masiva terminada con pendientes: 1 requiere intervención.",
        ),
        stats(pending=0, retry=0, failed=0, needs_human=1),
    )

    assert "Revisando todas las vacantes" in syncing.status_label
    assert completed.status_label == "Prueba final completada: cola en cero."
    assert attention.session_label == "Needs attention"
    assert "pendientes" in attention.status_label


def test_ui_surfaces_only_sanitized_indeed_diagnostic_path():
    detail = (
        "INDEED_CANDIDATE_NOT_FOUND — Diagnóstico local: "
        r"C:\Users\test\AppData\Local\ASIATI\ResumeAgent\diagnostics\indeed-ui-review.json"
    )
    ui=build_ui_state(
        snap("WAITING_FOR_HUMAN","Ada",detail),
        stats(needs_human=1),
    )
    assert ui.status_label == detail


def test_diagnostic_browser_failure_has_specific_recovery_instruction():
    ui = build_ui_state(snap("DIAGNOSTIC_BROWSER_FAILED"), stats())
    assert "Chrome" in ui.status_label
    assert "Open Indeed (Google Chrome)" in ui.status_label
    assert "conexión con el servicio" not in ui.status_label
