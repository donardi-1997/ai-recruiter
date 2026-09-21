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


def test_active_and_paused_labels():
    active=build_ui_state(snap("DOWNLOADING","Ada"), stats(claimed=1))
    paused=build_ui_state(snap("PAUSED"), stats())
    assert active.downloading == 1 and active.current_candidate == "Ada"
    assert active.status_label == "Descargando CV..."
    assert paused.status_label == "En pausa"


def test_manual_browser_open_has_explicit_safe_status():
    ui=build_ui_state(snap("MANUAL_BROWSER_OPEN"), stats())
    assert ui.status_label == "Cierra el navegador manual para continuar"
    assert ui.session_label == "Ready"


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


def test_ui_state_has_no_secret_fields():
    fields=set(UiState.__dataclass_fields__)
    forbidden={"token","lease_token","resume_url","gmail_address","raw_error"}
    assert fields.isdisjoint(forbidden)


def test_ui_surfaces_only_sanitized_indeed_diagnostic_path():
    detail = (
        "Indeed mostró una interfaz no reconocida. Diagnóstico local: "
        r"C:\Users\test\AppData\Local\ASIATI\ResumeAgent\diagnostics\indeed-ui-review.json"
    )
    ui=build_ui_state(
        snap("WAITING_FOR_HUMAN","Ada",detail),
        stats(needs_human=1),
    )
    assert ui.status_label == detail
