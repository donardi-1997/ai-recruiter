from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass

from .api_client import QueueStats, VacancySyncResult
from .vacancy_sync import collect_vacancy_snapshots
from .worker import WorkerSnapshot


@dataclass(frozen=True)
class UiState:
    session_label: str
    status_label: str
    pending: int
    downloading: int
    completed: int
    needs_attention: int
    retry: int
    failed: int
    current_candidate: str
    busy: bool = False


@dataclass(frozen=True)
class LayoutSpec:
    metric_columns: int
    sync_columns: int
    operation_columns: int
    max_content_width: int
    shell_padding: int


def _layout_for_width(width: int) -> LayoutSpec:
    safe_width = max(1, int(width))
    if safe_width >= 1080:
        return LayoutSpec(
            metric_columns=3,
            sync_columns=2,
            operation_columns=3,
            max_content_width=1120,
            shell_padding=20,
        )
    if safe_width >= 780:
        return LayoutSpec(
            metric_columns=2,
            sync_columns=1,
            operation_columns=2,
            max_content_width=safe_width,
            shell_padding=12,
        )
    return LayoutSpec(
        metric_columns=2,
        sync_columns=1,
        operation_columns=1,
        max_content_width=safe_width,
        shell_padding=10,
    )


_SAFE_HUMAN_CODE = re.compile(r"^(?:INDEED|RESUME)_[A-Z0-9_]{2,100}$")
_BUSY_STATES = {
    "DOWNLOADING",
    "SYNCING_JOBS",
    "SYNCING_APPLICATIONS",
    "DIAGNOSTIC_MODE",
}
_ATTENTION_STATES = {
    "WAITING_FOR_HUMAN",
    "LEASE_LOST",
    "FAILED",
    "FULL_SYNC_ATTENTION",
    "SYNC_FAILED",
    "JOBS_SYNC_ATTENTION",
}


def build_ui_state(snapshot: WorkerSnapshot, stats: QueueStats) -> UiState:
    state = snapshot.state
    session = "Necesita atención" if state in _ATTENTION_STATES else "Listo"
    labels = {
        "IDLE": "Esperando trabajo nuevo",
        "DOWNLOADING": "Descargando CV desde Indeed...",
        "COMPLETED": "CV cargado correctamente",
        "PAUSED": "Agente en pausa",
        "BROWSER_READY": "Chrome está abierto con el perfil del agente. Inicia sesión o resuelve la verificación y luego pulsa Continuar.",
        "MANUAL_BROWSER_OPEN": "Chrome está abierto con el perfil persistente del agente",
        "MANUAL_LOGIN_REQUIRED": "Indeed requiere verificación. Abre Indeed, inicia sesión o resuelve el CAPTCHA y luego pulsa Continuar.",
        "MANUAL_OPEN_FAILED": "No se pudo abrir Google Chrome con el perfil del agente",
        "DIAGNOSTIC_ANCHOR_FAILED": "Chrome no creó la pestaña de respaldo. Cierra Chrome y vuelve a abrir el diagnóstico.",
        "DIAGNOSTIC_MODE": "Modo diagnóstico activo. Usa Indeed normalmente y luego guarda el diagnóstico.",
        "DIAGNOSTIC_SAVED": "Diagnóstico guardado",
        "DIAGNOSTIC_BROWSER_FAILED": "No se pudo recuperar la sesión de Chrome del agente. Abre Indeed y vuelve a intentar.",
        "WAITING_FOR_HUMAN": "Indeed requiere intervención manual",
        "NEEDS_REVIEW_CONTINUE": "Caso apartado para revisión manual; continuando con la cola",
        "LEASE_LOST": "La tarea será reclamada de forma segura",
        "RETRY": "Reintento programado",
        "FAILED": "La tarea requiere revisión",
        "STOPPED": "Detenido",
        "ERROR": "Error de conexión con el servicio",
        "SYNCING_JOBS": "Actualizando vacantes y descripciones desde Indeed...",
        "JOBS_SYNC_COMPLETED": "Vacantes actualizadas",
        "JOBS_SYNC_ATTENTION": "La actualización de vacantes requiere atención",
        "SYNCING_APPLICATIONS": "Buscando postulaciones nuevas desde el último cursor...",
        "SYNC_READY": "Cambios sincronizados. Procesando únicamente CV pendientes o nuevos...",
        "FULL_SYNC_COMPLETED": "Sincronización incremental completada",
        "FULL_SYNC_ATTENTION": "Sincronización completada con casos por revisar",
        "SYNC_FAILED": "No fue posible preparar la sincronización incremental",
    }
    status_label = labels.get(state, "Procesando")
    diagnostic_marker = " — Diagnóstico local: "
    if state in {"WAITING_FOR_HUMAN", "NEEDS_REVIEW_CONTINUE"} and snapshot.last_error:
        if diagnostic_marker in snapshot.last_error:
            code, diagnostic_path = snapshot.last_error.split(diagnostic_marker, 1)
            if _SAFE_HUMAN_CODE.fullmatch(code) and diagnostic_path:
                status_label = snapshot.last_error
        elif _SAFE_HUMAN_CODE.fullmatch(snapshot.last_error):
            status_label = snapshot.last_error
    if state in {
        "DIAGNOSTIC_SAVED",
        "SYNC_READY",
        "FULL_SYNC_COMPLETED",
        "FULL_SYNC_ATTENTION",
        "JOBS_SYNC_COMPLETED",
        "JOBS_SYNC_ATTENTION",
        "SYNC_FAILED",
    } and snapshot.last_error:
        status_label = snapshot.last_error
    if state in {"RETRY", "FAILED", "ERROR"} and snapshot.last_error:
        status_label = snapshot.last_error
    elif (
        state == "IDLE"
        and stats.last_error_code
        and (stats.retry > 0 or stats.failed > 0)
    ):
        candidate = f" — {stats.last_error_candidate}" if stats.last_error_candidate else ""
        status_label = f"Último error: {stats.last_error_code}{candidate}"

    return UiState(
        session_label=session,
        status_label=status_label,
        pending=max(0, stats.pending),
        downloading=1 if state == "DOWNLOADING" else min(max(stats.claimed, 0), 1),
        completed=max(stats.completed, 0),
        needs_attention=max(stats.needs_human, 0),
        retry=max(stats.retry, 0),
        failed=max(stats.failed, 0),
        current_candidate=snapshot.active_candidate or "-",
        busy=state in _BUSY_STATES,
    )


def _vacancy_summary(result: VacancySyncResult) -> str:
    return (
        f"Vacantes: {result.discovered} encontradas · "
        f"{result.created} creadas · {result.updated} actualizadas · "
        f"{result.reconciled} reconciliadas · {result.unchanged} sin cambios · "
        f"{result.descriptions_recovered} descripciones recuperadas"
    )


def run_ui(*, worker, api, browser) -> None:
    import tkinter as tk
    from tkinter import ttk

    worker.pause()

    root = tk.Tk()
    root.title("ASIATI Resume Agent")
    root.geometry("1120x760")
    root.minsize(700, 620)

    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    style.configure("AgentTitle.TLabel", font=("Segoe UI", 20, "bold"))
    style.configure("AgentSubtitle.TLabel", font=("Segoe UI", 10))
    style.configure("MetricValue.TLabel", font=("Segoe UI", 18, "bold"))
    style.configure("MetricLabel.TLabel", font=("Segoe UI", 9))
    style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 10))
    style.configure("Secondary.TButton", padding=(10, 7))

    shell = ttk.Frame(root, padding=20)
    shell.pack(fill="both", expand=True)

    header = ttk.Frame(shell)
    header.pack(fill="x")
    header.columnconfigure(0, weight=1)
    title_box = ttk.Frame(header)
    title_box.grid(row=0, column=0, sticky="ew")
    ttk.Label(title_box, text="ASIATI Resume Agent", style="AgentTitle.TLabel").pack(anchor="w")
    ttk.Label(
        title_box,
        text="Indeed · vacantes, postulaciones y CVs",
        style="AgentSubtitle.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    session_var = tk.StringVar(value="Iniciando")
    session_box = ttk.LabelFrame(header, text="Sesión Indeed", padding=(14, 8))
    session_box.grid(row=0, column=1, sticky="e", padx=(12, 0))
    ttk.Label(session_box, textvariable=session_var, font=("Segoe UI", 10, "bold")).pack()

    status_var = tk.StringVar(value="Iniciando agente...")
    phase = ttk.LabelFrame(shell, text="Estado actual", padding=14)
    phase.pack(fill="x", pady=(18, 14))
    status_label_widget = ttk.Label(phase, textvariable=status_var, wraplength=980, font=("Segoe UI", 10))
    status_label_widget.pack(anchor="w")

    counters = {
        name: tk.StringVar(value="0")
        for name in ("pending", "downloading", "completed", "attention", "retry", "failed")
    }
    metrics = ttk.Frame(shell)
    metrics.pack(fill="x", pady=(0, 14))
    metric_defs = [
        ("Pendientes", "pending"),
        ("Procesando", "downloading"),
        ("Completados", "completed"),
        ("Atención", "attention"),
        ("Reintentos", "retry"),
        ("Fallidos", "failed"),
    ]
    metric_cards = []
    for label, key in metric_defs:
        card = ttk.LabelFrame(metrics, padding=(14, 10))
        metric_cards.append(card)
        ttk.Label(card, textvariable=counters[key], style="MetricValue.TLabel").pack(anchor="w")
        ttk.Label(card, text=label, style="MetricLabel.TLabel").pack(anchor="w")

    candidate_var = tk.StringVar(value="-")
    candidate_card = ttk.LabelFrame(shell, text="Candidato actual", padding=14)
    candidate_card.pack(fill="x", pady=(0, 14))
    candidate_label_widget = ttk.Label(candidate_card, textvariable=candidate_var, wraplength=980, font=("Segoe UI", 11, "bold"))
    candidate_label_widget.pack(anchor="w")

    commands: queue.Queue[str] = queue.Queue()
    updates: queue.Queue[UiState] = queue.Queue()
    stop_event = threading.Event()

    action_card = ttk.LabelFrame(shell, text="Sincronización", padding=14)
    action_card.pack(fill="x", pady=(0, 12))
    sync_all_button = ttk.Button(
        action_card,
        text="Sincronizar todo",
        style="Primary.TButton",
        command=lambda: commands.put("sync_all"),
    )
    sync_jobs_button = ttk.Button(
        action_card,
        text="Actualizar vacantes",
        style="Primary.TButton",
        command=lambda: commands.put("sync_jobs"),
    )
    sync_buttons = [sync_all_button, sync_jobs_button]

    operations = ttk.LabelFrame(shell, text="Operación", padding=12)
    operations.pack(fill="x", pady=(0, 12))
    pause_button = ttk.Button(operations, text="Pausar", style="Secondary.TButton", command=lambda: commands.put("pause"))
    resume_button = ttk.Button(operations, text="Continuar", style="Secondary.TButton", command=lambda: commands.put("resume"))
    retry_attention_button = ttk.Button(operations, text="Reintentar atención", style="Secondary.TButton", command=lambda: commands.put("retry_attention"))
    retry_failed_button = ttk.Button(operations, text="Reintentar fallidos", style="Secondary.TButton", command=lambda: commands.put("retry_failed"))
    open_button = ttk.Button(
        operations,
        text=f"Abrir Indeed ({browser.browser_label})",
        style="Secondary.TButton",
        command=lambda: commands.put("open"),
    )
    operation_buttons = [pause_button, resume_button, retry_attention_button, retry_failed_button, open_button]

    tools = ttk.LabelFrame(shell, text="Diagnóstico", padding=10)
    tools.pack(fill="x")
    diagnostic_start_button = ttk.Button(tools, text="Iniciar diagnóstico", command=lambda: commands.put("diagnostic_start"))
    diagnostic_stop_button = ttk.Button(tools, text="Guardar diagnóstico", command=lambda: commands.put("diagnostic_stop"))
    diagnostic_buttons = [diagnostic_start_button, diagnostic_stop_button]

    current_layout: LayoutSpec | None = None

    def place_grid(items, parent, columns: int, *, pady: int = 4) -> None:
        for column in range(max(len(items), 1)):
            parent.columnconfigure(column, weight=1 if column < columns else 0)
        for index, widget in enumerate(items):
            widget.grid(
                row=index // columns,
                column=index % columns,
                sticky="ew",
                padx=4,
                pady=pady,
            )

    def apply_layout(event=None) -> None:
        nonlocal current_layout
        if event is not None and event.widget is not root:
            return
        width = event.width if event is not None else root.winfo_width()
        layout = _layout_for_width(width)
        horizontal_padding = max(layout.shell_padding, (width - layout.max_content_width) // 2)
        shell.configure(padding=(horizontal_padding, layout.shell_padding))
        usable_width = max(320, min(width - (horizontal_padding * 2), layout.max_content_width))
        wraplength = max(280, usable_width - 48)
        status_label_widget.configure(wraplength=wraplength)
        candidate_label_widget.configure(wraplength=wraplength)

        previous_columns = None
        if current_layout is not None:
            previous_columns = (
                current_layout.metric_columns,
                current_layout.sync_columns,
                current_layout.operation_columns,
            )
        columns = (layout.metric_columns, layout.sync_columns, layout.operation_columns)
        if previous_columns == columns:
            current_layout = layout
            return

        place_grid(metric_cards, metrics, layout.metric_columns)
        place_grid(sync_buttons, action_card, layout.sync_columns, pady=3)
        place_grid(operation_buttons, operations, layout.operation_columns, pady=3)
        diagnostic_columns = 1 if layout.operation_columns == 1 else 2
        place_grid(diagnostic_buttons, tools, diagnostic_columns, pady=3)

        if layout.operation_columns == 1:
            session_box.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(10, 0))
        else:
            session_box.grid_configure(row=0, column=1, sticky="e", padx=(12, 0), pady=0)

        current_layout = layout

    root.bind("<Configure>", apply_layout, add="+")
    root.after_idle(apply_layout)

    conflict_buttons = [sync_all_button, sync_jobs_button, open_button, diagnostic_start_button]

    def publish(snapshot: WorkerSnapshot, stats: QueueStats) -> None:
        updates.put(build_ui_state(snapshot, stats))

    def sync_vacancies(last_stats: QueueStats) -> tuple[VacancySyncResult, QueueStats]:
        publish(
            WorkerSnapshot(
                "SYNCING_JOBS",
                worker.snapshot.active_candidate,
                worker.snapshot.processed_session,
                None,
            ),
            last_stats,
        )
        snapshots = collect_vacancy_snapshots(browser)
        result = api.sync_jobs(snapshots)
        refreshed_stats = api.stats()
        return result, refreshed_stats

    def agent_loop() -> None:
        last_stats = QueueStats(0, 0, 0, 0, 0, 0)
        diagnostic_snapshot: WorkerSnapshot | None = None
        full_sync_active = False
        full_sync_provider_pending = 0
        try:
            while not stop_event.is_set():
                while True:
                    try:
                        command = commands.get_nowait()
                    except queue.Empty:
                        break

                    if command == "pause":
                        worker.pause()
                        diagnostic_snapshot = None
                    elif command == "resume":
                        if browser.diagnostic_active:
                            publish(
                                WorkerSnapshot("DIAGNOSTIC_MODE", worker.snapshot.active_candidate, worker.snapshot.processed_session, None),
                                last_stats,
                            )
                            continue
                        diagnostic_snapshot = None
                        try:
                            worker.resume()
                        except Exception:
                            pass
                    elif command == "sync_jobs":
                        if browser.diagnostic_active or worker.snapshot.state == "DOWNLOADING":
                            continue
                        was_paused = worker.snapshot.state == "PAUSED"
                        worker.pause()
                        try:
                            result, last_stats = sync_vacancies(last_stats)
                            diagnostic_snapshot = WorkerSnapshot(
                                "JOBS_SYNC_COMPLETED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                _vacancy_summary(result),
                            )
                        except RuntimeError as exc:
                            detail = str(exc)
                            if detail == "INDEED_AUTH_REQUIRED":
                                diagnostic_snapshot = WorkerSnapshot(
                                    "JOBS_SYNC_ATTENTION",
                                    worker.snapshot.active_candidate,
                                    worker.snapshot.processed_session,
                                    "Indeed requiere inicio de sesión o verificación antes de actualizar vacantes.",
                                )
                            else:
                                diagnostic_snapshot = WorkerSnapshot("JOBS_SYNC_ATTENTION", None, worker.snapshot.processed_session, "No fue posible actualizar las vacantes de Indeed.")
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot("JOBS_SYNC_ATTENTION", None, worker.snapshot.processed_session, "No fue posible actualizar las vacantes de Indeed.")
                        publish(diagnostic_snapshot, last_stats)
                        if not was_paused and diagnostic_snapshot.state == "JOBS_SYNC_COMPLETED":
                            diagnostic_snapshot = None
                            try:
                                worker.resume()
                            except Exception:
                                pass
                    elif command == "sync_all":
                        if browser.diagnostic_active or worker.snapshot.state == "DOWNLOADING":
                            continue
                        diagnostic_snapshot = None
                        worker.pause()
                        try:
                            jobs_result, last_stats = sync_vacancies(last_stats)
                            publish(
                                WorkerSnapshot(
                                    "SYNCING_APPLICATIONS",
                                    worker.snapshot.active_candidate,
                                    worker.snapshot.processed_session,
                                    None,
                                ),
                                last_stats,
                            )
                            result = api.sync_all()
                            last_stats = api.stats()
                            full_sync_active = True
                            full_sync_provider_pending = result.reconcile_provider_pending
                            detail = (
                                f"{_vacancy_summary(jobs_result)} · "
                                f"{result.created} postulaciones nuevas · "
                                f"{result.reconcile_queued} tareas de respaldo nuevas · "
                                f"cola pendiente: {last_stats.pending}."
                            )
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_READY",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                detail,
                            )
                            publish(diagnostic_snapshot, last_stats)
                            diagnostic_snapshot = None
                            worker.resume()
                        except RuntimeError as exc:
                            full_sync_active = False
                            detail = str(exc)
                            diagnostic_snapshot = WorkerSnapshot(
                                "JOBS_SYNC_ATTENTION" if detail == "INDEED_AUTH_REQUIRED" else "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                            publish(diagnostic_snapshot, last_stats)
                        except Exception:
                            full_sync_active = False
                            diagnostic_snapshot = WorkerSnapshot("SYNC_FAILED", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                            publish(diagnostic_snapshot, last_stats)
                    elif command == "retry_failed":
                        if browser.diagnostic_active:
                            continue
                        diagnostic_snapshot = None
                        try:
                            api.retry_failed()
                            last_stats = api.stats()
                        except Exception:
                            pass
                        publish(worker.snapshot, last_stats)
                    elif command == "retry_attention":
                        if browser.diagnostic_active:
                            continue
                        diagnostic_snapshot = None
                        try:
                            api.retry_attention()
                            last_stats = api.stats()
                            worker.reset_after_attention_retry()
                        except Exception:
                            pass
                        publish(worker.snapshot, last_stats)
                    elif command == "diagnostic_start":
                        worker.pause()
                        try:
                            browser.start_diagnostic()
                            diagnostic_snapshot = WorkerSnapshot("DIAGNOSTIC_MODE", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                        except RuntimeError as exc:
                            state = "MANUAL_LOGIN_REQUIRED" if str(exc) == "INDEED_MANUAL_LOGIN_REQUIRED" else "ERROR"
                            diagnostic_snapshot = WorkerSnapshot(state, worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot("DIAGNOSTIC_BROWSER_FAILED", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                        publish(diagnostic_snapshot, last_stats)
                    elif command == "diagnostic_stop":
                        path = None
                        try:
                            path = browser.stop_diagnostic()
                        except Exception:
                            pass
                        detail = f"Diagnóstico guardado: {path}" if path else "No fue posible guardar el diagnóstico."
                        diagnostic_snapshot = WorkerSnapshot("DIAGNOSTIC_SAVED", worker.snapshot.active_candidate, worker.snapshot.processed_session, detail)
                        publish(diagnostic_snapshot, last_stats)
                    elif command == "open":
                        diagnostic_snapshot = None
                        worker.pause()
                        try:
                            browser.open_indeed()
                            diagnostic_snapshot = WorkerSnapshot("BROWSER_READY", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot("MANUAL_OPEN_FAILED", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                        publish(diagnostic_snapshot, last_stats)

                if browser.diagnostic_active:
                    try:
                        browser.poll_diagnostic()
                    except RuntimeError:
                        diagnostic_snapshot = WorkerSnapshot("MANUAL_LOGIN_REQUIRED", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                    except Exception:
                        diagnostic_snapshot = WorkerSnapshot("ERROR", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                    snapshot = diagnostic_snapshot or WorkerSnapshot("DIAGNOSTIC_MODE", worker.snapshot.active_candidate, worker.snapshot.processed_session, None)
                    try:
                        last_stats = api.stats()
                    except Exception:
                        pass
                    publish(snapshot, last_stats)
                elif diagnostic_snapshot is not None:
                    snapshot = diagnostic_snapshot
                    try:
                        last_stats = api.stats()
                    except Exception:
                        pass
                    publish(snapshot, last_stats)
                else:
                    try:
                        snapshot = worker.run_once()
                        last_stats = api.stats()
                        if (
                            full_sync_active
                            and snapshot.state == "IDLE"
                            and last_stats.pending == 0
                            and last_stats.claimed == 0
                            and last_stats.retry == 0
                        ):
                            if last_stats.needs_human or last_stats.failed or full_sync_provider_pending:
                                detail = (
                                    "Sincronización incremental terminada con pendientes: "
                                    f"{last_stats.needs_human} requieren intervención, "
                                    f"{last_stats.failed} fallaron y "
                                    f"{full_sync_provider_pending} siguen en procesamiento automático."
                                )
                                snapshot = WorkerSnapshot("FULL_SYNC_ATTENTION", None, worker.snapshot.processed_session, detail)
                            else:
                                detail = (
                                    "Sincronización incremental completada: no queda trabajo pendiente y "
                                    f"{last_stats.completed} CV figuran completados."
                                )
                                snapshot = WorkerSnapshot("FULL_SYNC_COMPLETED", None, worker.snapshot.processed_session, detail)
                            full_sync_active = False
                        publish(snapshot, last_stats)
                    except Exception:
                        snapshot = WorkerSnapshot("ERROR", None, worker.snapshot.processed_session, None)
                        publish(snapshot, last_stats)

                delay = 0.5 if snapshot.state not in {"IDLE", "PAUSED", "WAITING_FOR_HUMAN", "JOBS_SYNC_COMPLETED"} else 2.0
                stop_event.wait(delay)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    agent_thread = threading.Thread(target=agent_loop, name="asiati-resume-agent", daemon=True)
    agent_thread.start()

    def drain_updates() -> None:
        try:
            while True:
                ui = updates.get_nowait()
                session_var.set(ui.session_label)
                status_var.set(ui.status_label)
                candidate_var.set(ui.current_candidate)
                counters["pending"].set(str(ui.pending))
                counters["downloading"].set(str(ui.downloading))
                counters["completed"].set(str(ui.completed))
                counters["attention"].set(str(ui.needs_attention))
                counters["retry"].set(str(ui.retry))
                counters["failed"].set(str(ui.failed))
                state = "disabled" if ui.busy else "normal"
                for button in conflict_buttons:
                    button.configure(state=state)
        except queue.Empty:
            pass
        if not stop_event.is_set():
            root.after(250, drain_updates)

    def on_close() -> None:
        worker.stop()
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(250, drain_updates)
    root.mainloop()
    stop_event.set()
    agent_thread.join(timeout=5.0)