from __future__ import annotations

import queue
import re
import threading

from .api_client import QueueStats
from .sync_services import CandidateSyncService, VacancySyncReport, VacancySyncService
from .ui_v2 import LayoutSpec, UiState, _layout_for_width, _vacancy_summary, build_ui_state
from .worker import WorkerSnapshot

_SAFE_CODE = re.compile(r"^(?:INDEED|RESUME)_[A-Z0-9_]{2,100}$")


def _safe_code(value: object, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_CODE.fullmatch(candidate) else fallback


def _vacancy_report_summary(report: VacancySyncReport) -> str:
    base = _vacancy_summary(report.result)
    crawl = (
        f"Indeed: {report.discovered} descubiertas"
        f"/{report.expected_total or report.discovered} esperadas · "
        f"{report.hydrated} detalles con descripción · "
        f"{report.detail_failures} detalles omitidos"
    )
    if report.warning_code:
        return f"{base} · {crawl} · {report.warning_code}"
    return f"{base} · {crawl}"


def _candidate_summary(report) -> str:
    result = report.result
    return (
        f"Candidatos: {result.created} postulaciones nuevas · "
        f"{result.existing} existentes · {result.needs_review} por revisar · "
        f"{result.reconcile_queued} tareas de CV nuevas · "
        f"cola pendiente: {report.stats.pending}."
    )


def run_ui(*, worker, api, browser) -> None:
    import tkinter as tk
    from tkinter import ttk

    worker.pause()
    vacancy_service = VacancySyncService(api=api, browser=browser)
    candidate_service = CandidateSyncService(api=api)

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
    status_label_widget = ttk.Label(
        phase,
        textvariable=status_var,
        wraplength=980,
        font=("Segoe UI", 10),
    )
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
    candidate_label_widget = ttk.Label(
        candidate_card,
        textvariable=candidate_var,
        wraplength=980,
        font=("Segoe UI", 11, "bold"),
    )
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
    sync_candidates_button = ttk.Button(
        action_card,
        text="Actualizar candidatos",
        style="Primary.TButton",
        command=lambda: commands.put("sync_candidates"),
    )
    sync_buttons = [sync_all_button, sync_jobs_button, sync_candidates_button]

    operations = ttk.LabelFrame(shell, text="Operación", padding=12)
    operations.pack(fill="x", pady=(0, 12))
    pause_button = ttk.Button(
        operations,
        text="Pausar",
        style="Secondary.TButton",
        command=lambda: commands.put("pause"),
    )
    resume_button = ttk.Button(
        operations,
        text="Continuar",
        style="Secondary.TButton",
        command=lambda: commands.put("resume"),
    )
    retry_attention_button = ttk.Button(
        operations,
        text="Reintentar atención",
        style="Secondary.TButton",
        command=lambda: commands.put("retry_attention"),
    )
    retry_failed_button = ttk.Button(
        operations,
        text="Reintentar fallidos",
        style="Secondary.TButton",
        command=lambda: commands.put("retry_failed"),
    )
    open_button = ttk.Button(
        operations,
        text=f"Abrir Indeed ({browser.browser_label})",
        style="Secondary.TButton",
        command=lambda: commands.put("open"),
    )
    operation_buttons = [
        pause_button,
        resume_button,
        retry_attention_button,
        retry_failed_button,
        open_button,
    ]

    tools = ttk.LabelFrame(shell, text="Diagnóstico", padding=10)
    tools.pack(fill="x")
    diagnostic_start_button = ttk.Button(
        tools,
        text="Iniciar diagnóstico",
        command=lambda: commands.put("diagnostic_start"),
    )
    diagnostic_stop_button = ttk.Button(
        tools,
        text="Guardar diagnóstico",
        command=lambda: commands.put("diagnostic_stop"),
    )
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
        sync_columns = 3 if width >= 1080 else layout.sync_columns
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
        columns = (layout.metric_columns, sync_columns, layout.operation_columns)
        if previous_columns != columns:
            place_grid(metric_cards, metrics, layout.metric_columns)
            place_grid(sync_buttons, action_card, sync_columns, pady=3)
            place_grid(operation_buttons, operations, layout.operation_columns, pady=3)
            diagnostic_columns = 1 if layout.operation_columns == 1 else 2
            place_grid(diagnostic_buttons, tools, diagnostic_columns, pady=3)

        if layout.operation_columns == 1:
            session_box.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(10, 0))
        else:
            session_box.grid_configure(row=0, column=1, sticky="e", padx=(12, 0), pady=0)

        current_layout = LayoutSpec(
            metric_columns=layout.metric_columns,
            sync_columns=sync_columns,
            operation_columns=layout.operation_columns,
            max_content_width=layout.max_content_width,
            shell_padding=layout.shell_padding,
        )

    root.bind("<Configure>", apply_layout, add="+")
    root.after_idle(apply_layout)

    conflict_buttons = [
        sync_all_button,
        sync_jobs_button,
        sync_candidates_button,
        open_button,
        diagnostic_start_button,
    ]

    def publish(snapshot: WorkerSnapshot, stats: QueueStats) -> None:
        updates.put(build_ui_state(snapshot, stats))

    def publish_phase(state: str, stats: QueueStats, detail: str | None = None) -> None:
        publish(
            WorkerSnapshot(
                state,
                worker.snapshot.active_candidate,
                worker.snapshot.processed_session,
                detail,
            ),
            stats,
        )

    def run_vacancies(last_stats: QueueStats) -> VacancySyncReport:
        publish_phase("SYNCING_JOBS", last_stats)
        return vacancy_service.run()

    def run_candidates(last_stats: QueueStats):
        publish_phase("SYNCING_APPLICATIONS", last_stats)
        return candidate_service.run()

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
                            publish_phase("DIAGNOSTIC_MODE", last_stats)
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
                            report = run_vacancies(last_stats)
                            last_stats = report.stats
                            detail = _vacancy_report_summary(report)
                            state = "JOBS_SYNC_ATTENTION" if report.warning_code else "JOBS_SYNC_COMPLETED"
                            diagnostic_snapshot = WorkerSnapshot(
                                state,
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                detail,
                            )
                        except RuntimeError as exc:
                            code = _safe_code(exc, "INDEED_JOB_SYNC_FAILED")
                            detail = (
                                "Indeed requiere inicio de sesión o verificación antes de actualizar vacantes."
                                if code == "INDEED_AUTH_REQUIRED"
                                else f"Vacantes detenidas en etapa técnica: {code}"
                            )
                            diagnostic_snapshot = WorkerSnapshot(
                                "JOBS_SYNC_ATTENTION",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                detail,
                            )
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot(
                                "JOBS_SYNC_ATTENTION",
                                None,
                                worker.snapshot.processed_session,
                                "Vacantes detenidas en etapa técnica: INDEED_JOB_SYNC_FAILED",
                            )
                        publish(diagnostic_snapshot, last_stats)
                        if not was_paused and diagnostic_snapshot.state == "JOBS_SYNC_COMPLETED":
                            diagnostic_snapshot = None
                            try:
                                worker.resume()
                            except Exception:
                                pass

                    elif command == "sync_candidates":
                        if browser.diagnostic_active or worker.snapshot.state == "DOWNLOADING":
                            continue
                        diagnostic_snapshot = None
                        worker.pause()
                        try:
                            report = run_candidates(last_stats)
                            last_stats = report.stats
                            full_sync_active = True
                            full_sync_provider_pending = report.result.reconcile_provider_pending
                            detail = _candidate_summary(report)
                            publish_phase("SYNC_READY", last_stats, detail)
                            worker.resume()
                        except RuntimeError as exc:
                            full_sync_active = False
                            code = _safe_code(exc, "INDEED_CANDIDATE_SYNC_FAILED")
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                f"Candidatos detenidos: {code}",
                            )
                            publish(diagnostic_snapshot, last_stats)
                        except Exception:
                            full_sync_active = False
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                "Candidatos detenidos: INDEED_CANDIDATE_SYNC_FAILED",
                            )
                            publish(diagnostic_snapshot, last_stats)

                    elif command == "sync_all":
                        if browser.diagnostic_active or worker.snapshot.state == "DOWNLOADING":
                            continue
                        diagnostic_snapshot = None
                        worker.pause()
                        vacancy_detail = "Vacantes no actualizadas"
                        try:
                            vacancy_report = run_vacancies(last_stats)
                            last_stats = vacancy_report.stats
                            vacancy_detail = _vacancy_report_summary(vacancy_report)
                        except RuntimeError as exc:
                            code = _safe_code(exc, "INDEED_JOB_SYNC_FAILED")
                            if code == "INDEED_AUTH_REQUIRED":
                                diagnostic_snapshot = WorkerSnapshot(
                                    "JOBS_SYNC_ATTENTION",
                                    worker.snapshot.active_candidate,
                                    worker.snapshot.processed_session,
                                    "Indeed requiere inicio de sesión o verificación antes de sincronizar.",
                                )
                                publish(diagnostic_snapshot, last_stats)
                                continue
                            vacancy_detail = f"Vacantes con advertencia: {code}"
                        except Exception:
                            vacancy_detail = "Vacantes con advertencia: INDEED_JOB_SYNC_FAILED"

                        try:
                            candidate_report = run_candidates(last_stats)
                            last_stats = candidate_report.stats
                            full_sync_active = True
                            full_sync_provider_pending = candidate_report.result.reconcile_provider_pending
                            detail = f"{vacancy_detail} · {_candidate_summary(candidate_report)}"
                            publish_phase("SYNC_READY", last_stats, detail)
                            worker.resume()
                        except RuntimeError as exc:
                            full_sync_active = False
                            code = _safe_code(exc, "INDEED_CANDIDATE_SYNC_FAILED")
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                f"{vacancy_detail} · Candidatos detenidos: {code}",
                            )
                            publish(diagnostic_snapshot, last_stats)
                        except Exception:
                            full_sync_active = False
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                f"{vacancy_detail} · Candidatos detenidos: INDEED_CANDIDATE_SYNC_FAILED",
                            )
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
                            diagnostic_snapshot = WorkerSnapshot(
                                "DIAGNOSTIC_MODE",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        except RuntimeError as exc:
                            state = (
                                "MANUAL_LOGIN_REQUIRED"
                                if str(exc) == "INDEED_MANUAL_LOGIN_REQUIRED"
                                else "ERROR"
                            )
                            diagnostic_snapshot = WorkerSnapshot(
                                state,
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot(
                                "DIAGNOSTIC_BROWSER_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        publish(diagnostic_snapshot, last_stats)

                    elif command == "diagnostic_stop":
                        path = None
                        try:
                            path = browser.stop_diagnostic()
                        except Exception:
                            pass
                        detail = (
                            f"Diagnóstico guardado: {path}"
                            if path
                            else "No fue posible guardar el diagnóstico."
                        )
                        diagnostic_snapshot = WorkerSnapshot(
                            "DIAGNOSTIC_SAVED",
                            worker.snapshot.active_candidate,
                            worker.snapshot.processed_session,
                            detail,
                        )
                        publish(diagnostic_snapshot, last_stats)

                    elif command == "open":
                        diagnostic_snapshot = None
                        worker.pause()
                        try:
                            browser.open_indeed()
                            diagnostic_snapshot = WorkerSnapshot(
                                "BROWSER_READY",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        except Exception:
                            diagnostic_snapshot = WorkerSnapshot(
                                "MANUAL_OPEN_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        publish(diagnostic_snapshot, last_stats)

                if browser.diagnostic_active:
                    try:
                        browser.poll_diagnostic()
                    except RuntimeError:
                        diagnostic_snapshot = WorkerSnapshot(
                            "MANUAL_LOGIN_REQUIRED",
                            worker.snapshot.active_candidate,
                            worker.snapshot.processed_session,
                            None,
                        )
                    except Exception:
                        diagnostic_snapshot = WorkerSnapshot(
                            "ERROR",
                            worker.snapshot.active_candidate,
                            worker.snapshot.processed_session,
                            None,
                        )
                    snapshot = diagnostic_snapshot or WorkerSnapshot(
                        "DIAGNOSTIC_MODE",
                        worker.snapshot.active_candidate,
                        worker.snapshot.processed_session,
                        None,
                    )
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
                                    "Sincronización de candidatos terminada con pendientes: "
                                    f"{last_stats.needs_human} requieren intervención, "
                                    f"{last_stats.failed} fallaron y "
                                    f"{full_sync_provider_pending} siguen en procesamiento automático."
                                )
                                snapshot = WorkerSnapshot(
                                    "FULL_SYNC_ATTENTION",
                                    None,
                                    worker.snapshot.processed_session,
                                    detail,
                                )
                            else:
                                detail = (
                                    "Sincronización de candidatos completada: no queda trabajo pendiente y "
                                    f"{last_stats.completed} CV figuran completados."
                                )
                                snapshot = WorkerSnapshot(
                                    "FULL_SYNC_COMPLETED",
                                    None,
                                    worker.snapshot.processed_session,
                                    detail,
                                )
                            full_sync_active = False
                        publish(snapshot, last_stats)
                    except Exception:
                        snapshot = WorkerSnapshot(
                            "ERROR",
                            None,
                            worker.snapshot.processed_session,
                            None,
                        )
                        publish(snapshot, last_stats)

                delay = (
                    0.5
                    if snapshot.state not in {"IDLE", "PAUSED", "WAITING_FOR_HUMAN", "JOBS_SYNC_COMPLETED"}
                    else 2.0
                )
                stop_event.wait(delay)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    agent_thread = threading.Thread(
        target=agent_loop,
        name="asiati-resume-agent",
        daemon=True,
    )
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
