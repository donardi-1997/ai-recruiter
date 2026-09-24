from __future__ import annotations

import queue
import re
import threading

from .api_client import QueueStats
from .sync_services import CandidateSyncService, VacancySyncReport, VacancySyncService
from .ui_v2 import LayoutSpec, UiState, _vacancy_summary, build_ui_state
from .worker import WorkerSnapshot

_SAFE_CODE = re.compile(r"^(?:GMAIL|INDEED|RESUME)_[A-Z0-9_]{2,100}$")

_UI = {
    "bg": "#F4F7FB",
    "surface": "#FFFFFF",
    "border": "#D7DFEA",
    "text": "#172033",
    "muted": "#667085",
    "brand": "#2457D6",
    "brand_hover": "#1E4EBB",
    "brand_pressed": "#193F98",
    "soft": "#F8FAFC",
    "disabled_bg": "#E9EDF3",
    "disabled_fg": "#98A2B3",
}

_STATUS_PALETTES = {
    "ready": ("#ECFDF3", "#ABEFC6", "#067647"),
    "active": ("#EEF4FF", "#B2CCFF", "#2457D6"),
    "warning": ("#FFFAEB", "#FEDF89", "#B54708"),
    "danger": ("#FEF3F2", "#FECDCA", "#B42318"),
}

_METRIC_PALETTES = {
    "pending": ("#F8FAFC", "#D7DFEA", "#344054", "#667085"),
    "downloading": ("#EEF4FF", "#B2CCFF", "#2457D6", "#475467"),
    "completed": ("#ECFDF3", "#ABEFC6", "#067647", "#475467"),
    "attention": ("#FFFAEB", "#FEDF89", "#B54708", "#475467"),
    "retry": ("#F4F3FF", "#D9D6FE", "#6938EF", "#475467"),
    "failed": ("#FEF3F2", "#FECDCA", "#B42318", "#475467"),
}


def _layout_for_width(width: int) -> LayoutSpec:
    """Presentation layout used by the active v3 desktop UI."""

    safe_width = max(1, int(width))
    if safe_width >= 1080:
        return LayoutSpec(
            metric_columns=3,
            sync_columns=3,
            operation_columns=3,
            max_content_width=980,
            shell_padding=18,
        )
    if safe_width >= 780:
        return LayoutSpec(
            metric_columns=3,
            sync_columns=3,
            operation_columns=3,
            max_content_width=max(320, min(820, safe_width - 20)),
            shell_padding=12,
        )
    return LayoutSpec(
        metric_columns=2,
        sync_columns=1,
        operation_columns=2,
        max_content_width=max(320, safe_width - 20),
        shell_padding=10,
    )


def _status_tone(ui: UiState) -> str:
    if ui.failed > 0:
        return "danger"
    if ui.needs_attention > 0 or ui.session_label == "Necesita atención":
        return "warning"
    if ui.busy or ui.downloading > 0:
        return "active"
    return "ready"


def _safe_code(value: object, fallback: str) -> str:
    explicit_code = str(getattr(value, "code", "") or "").strip()
    if _SAFE_CODE.fullmatch(explicit_code):
        return explicit_code
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
    root.geometry("980x640")
    root.minsize(720, 540)
    root.configure(background=_UI["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("App.TFrame", background=_UI["bg"])
    style.configure("AgentTitle.TLabel", background=_UI["bg"], foreground=_UI["text"], font=("Segoe UI", 19, "bold"))
    style.configure("AgentSubtitle.TLabel", background=_UI["bg"], foreground=_UI["muted"], font=("Segoe UI", 9))
    style.configure(
        "Section.TLabelframe",
        background=_UI["surface"],
        bordercolor=_UI["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "Section.TLabelframe.Label",
        background=_UI["surface"],
        foreground=_UI["muted"],
        font=("Segoe UI", 9, "bold"),
    )
    style.configure(
        "Primary.TButton",
        background=_UI["brand"],
        foreground="#FFFFFF",
        font=("Segoe UI", 9, "bold"),
        padding=(14, 9),
        borderwidth=0,
        relief="flat",
        anchor="center",
    )
    style.map(
        "Primary.TButton",
        background=[
            ("disabled", _UI["disabled_bg"]),
            ("pressed", _UI["brand_pressed"]),
            ("active", _UI["brand_hover"]),
        ],
        foreground=[("disabled", _UI["disabled_fg"]), ("!disabled", "#FFFFFF")],
    )
    style.configure(
        "Secondary.TButton",
        background=_UI["surface"],
        foreground="#344054",
        font=("Segoe UI", 9),
        padding=(11, 8),
        borderwidth=1,
        relief="solid",
        anchor="center",
    )
    style.map(
        "Secondary.TButton",
        background=[
            ("disabled", _UI["disabled_bg"]),
            ("pressed", "#EAECF0"),
            ("active", "#F2F4F7"),
        ],
        foreground=[("disabled", _UI["disabled_fg"]), ("!disabled", "#344054")],
    )
    style.configure(
        "Tertiary.TButton",
        background=_UI["soft"],
        foreground="#475467",
        font=("Segoe UI", 9),
        padding=(10, 7),
        borderwidth=1,
        relief="solid",
        anchor="center",
    )
    style.map(
        "Tertiary.TButton",
        background=[("pressed", "#EAECF0"), ("active", "#F2F4F7")],
    )

    viewport = ttk.Frame(root, style="App.TFrame")
    viewport.pack(fill="both", expand=True)

    canvas = tk.Canvas(
        viewport,
        background=_UI["bg"],
        highlightthickness=0,
        bd=0,
        relief="flat",
        yscrollincrement=16,
    )
    scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    shell = ttk.Frame(canvas, style="App.TFrame", padding=18)
    shell_window = canvas.create_window((0, 0), window=shell, anchor="nw")

    def sync_scrollregion(event=None) -> None:
        bounds = canvas.bbox("all")
        if bounds is not None:
            canvas.configure(scrollregion=bounds)

    def fit_shell_to_canvas(event) -> None:
        canvas.itemconfigure(shell_window, width=max(1, event.width))
        sync_scrollregion()

    def on_mousewheel(event):
        bounds = canvas.bbox("all")
        if bounds is None or bounds[3] <= canvas.winfo_height():
            return None
        units = int(-event.delta / 120)
        if units == 0:
            units = -1 if event.delta > 0 else 1
        canvas.yview_scroll(units * 3, "units")
        return "break"

    shell.bind("<Configure>", sync_scrollregion, add="+")
    canvas.bind("<Configure>", fit_shell_to_canvas, add="+")
    root.bind("<MouseWheel>", on_mousewheel, add="+")

    header = ttk.Frame(shell, style="App.TFrame")
    header.pack(fill="x")
    header.columnconfigure(0, weight=1)
    title_box = ttk.Frame(header, style="App.TFrame")
    title_box.grid(row=0, column=0, sticky="ew")
    ttk.Label(title_box, text="ASIATI Resume Agent", style="AgentTitle.TLabel").pack(anchor="w")
    ttk.Label(
        title_box,
        text="Indeed · vacantes, postulaciones y CVs",
        style="AgentSubtitle.TLabel",
    ).pack(anchor="w", pady=(1, 0))

    session_var = tk.StringVar(value="Iniciando")
    session_box = tk.Frame(
        header,
        background=_UI["surface"],
        highlightthickness=1,
        highlightbackground=_UI["border"],
        bd=0,
        padx=10,
        pady=6,
    )
    session_box.grid(row=0, column=1, sticky="e", padx=(10, 0))
    session_heading_widget = tk.Label(
        session_box,
        text="SESIÓN INDEED",
        background=_UI["surface"],
        foreground=_UI["muted"],
        font=("Segoe UI", 8, "bold"),
        anchor="w",
    )
    session_heading_widget.pack(fill="x")
    session_value_widget = tk.Label(
        session_box,
        textvariable=session_var,
        background=_UI["surface"],
        foreground=_UI["text"],
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    )
    session_value_widget.pack(fill="x", pady=(1, 0))

    status_var = tk.StringVar(value="Iniciando agente...")
    status_bg, status_border, status_fg = _STATUS_PALETTES["active"]
    phase = tk.Frame(
        shell,
        background=status_bg,
        highlightthickness=1,
        highlightbackground=status_border,
        bd=0,
        padx=14,
        pady=9,
    )
    phase.pack(fill="x", pady=(10, 8))
    status_heading_widget = tk.Label(
        phase,
        text="ESTADO ACTUAL",
        background=status_bg,
        foreground=status_fg,
        font=("Segoe UI", 8, "bold"),
        anchor="w",
    )
    status_heading_widget.pack(fill="x", anchor="w")
    status_label_widget = tk.Label(
        phase,
        textvariable=status_var,
        wraplength=900,
        justify="left",
        anchor="w",
        background=status_bg,
        foreground=_UI["text"],
        font=("Segoe UI", 9),
    )
    status_label_widget.pack(fill="x", anchor="w", pady=(3, 0))

    counters = {
        name: tk.StringVar(value="0")
        for name in ("pending", "downloading", "completed", "attention", "retry", "failed")
    }
    metrics = ttk.Frame(shell, style="App.TFrame")
    metrics.pack(fill="x", pady=(0, 8))
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
        metric_bg, metric_border, value_fg, label_fg = _METRIC_PALETTES[key]
        card = tk.Frame(
            metrics,
            background=metric_bg,
            highlightthickness=1,
            highlightbackground=metric_border,
            bd=0,
            padx=12,
            pady=8,
        )
        metric_cards.append(card)
        tk.Label(
            card,
            textvariable=counters[key],
            background=metric_bg,
            foreground=value_fg,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            text=label,
            background=metric_bg,
            foreground=label_fg,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(1, 0))

    candidate_var = tk.StringVar(value="-")
    candidate_card = ttk.LabelFrame(shell, text="Candidato actual", style="Section.TLabelframe", padding=10)
    candidate_card.pack(fill="x", pady=(0, 8))
    candidate_label_widget = ttk.Label(
        candidate_card,
        textvariable=candidate_var,
        wraplength=900,
        font=("Segoe UI", 10, "bold"),
    )
    candidate_label_widget.pack(anchor="w")

    commands: queue.Queue[str] = queue.Queue()
    updates: queue.Queue[UiState] = queue.Queue()
    stop_event = threading.Event()
    pause_requested = threading.Event()
    pause_feedback_pending = threading.Event()

    def request_pause() -> None:
        if pause_requested.is_set():
            return
        pause_requested.set()
        pause_feedback_pending.set()
        status_var.set("Pausa solicitada · terminando operación actual…")
        pause_button.configure(state="disabled")
        commands.put("pause")

    def request_resume() -> None:
        pause_requested.clear()
        pause_feedback_pending.clear()
        status_var.set("Reanudando agente…")
        pause_button.configure(state="normal")
        commands.put("resume")

    action_card = ttk.LabelFrame(shell, text="Sincronización", style="Section.TLabelframe", padding=9)
    action_card.pack(fill="x", pady=(0, 8))
    sync_all_button = ttk.Button(
        action_card,
        text="Sincronizar todo",
        style="Primary.TButton",
        command=lambda: commands.put("sync_all"),
    )
    sync_jobs_button = ttk.Button(
        action_card,
        text="Actualizar vacantes",
        style="Secondary.TButton",
        command=lambda: commands.put("sync_jobs"),
    )
    sync_candidates_button = ttk.Button(
        action_card,
        text="Actualizar candidatos",
        style="Secondary.TButton",
        command=lambda: commands.put("sync_candidates"),
    )
    sync_buttons = [sync_all_button, sync_jobs_button, sync_candidates_button]

    operations = ttk.LabelFrame(shell, text="Operación", style="Section.TLabelframe", padding=9)
    operations.pack(fill="x", pady=(0, 8))
    pause_button = ttk.Button(
        operations,
        text="Pausar",
        style="Secondary.TButton",
        command=request_pause,
    )
    resume_button = ttk.Button(
        operations,
        text="Continuar",
        style="Secondary.TButton",
        command=request_resume,
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

    tools = ttk.LabelFrame(shell, text="Diagnóstico", style="Section.TLabelframe", padding=8)
    tools.pack(fill="x")
    diagnostic_start_button = ttk.Button(
        tools,
        text="Iniciar diagnóstico",
        style="Tertiary.TButton",
        command=lambda: commands.put("diagnostic_start"),
    )
    diagnostic_stop_button = ttk.Button(
        tools,
        text="Guardar diagnóstico",
        style="Tertiary.TButton",
        command=lambda: commands.put("diagnostic_stop"),
    )
    diagnostic_buttons = [diagnostic_start_button, diagnostic_stop_button]

    current_layout: LayoutSpec | None = None

    def place_grid(items, parent, columns: int, *, pady: int = 3) -> None:
        for column in range(max(len(items), 1)):
            parent.columnconfigure(column, weight=1 if column < columns else 0)
        for index, widget in enumerate(items):
            widget.grid(
                row=index // columns,
                column=index % columns,
                sticky="ew",
                padx=3,
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
        wraplength = max(280, usable_width - 32)
        status_label_widget.configure(wraplength=wraplength)
        candidate_label_widget.configure(wraplength=wraplength)

        previous_columns = None
        if current_layout is not None:
            previous_columns = (
                current_layout.metric_columns,
                current_layout.sync_columns,
                current_layout.operation_columns,
            )
        columns = (
            layout.metric_columns,
            layout.sync_columns,
            layout.operation_columns,
        )
        if previous_columns != columns:
            place_grid(metric_cards, metrics, layout.metric_columns)
            place_grid(sync_buttons, action_card, layout.sync_columns)
            place_grid(operation_buttons, operations, layout.operation_columns)
            diagnostic_columns = 1 if layout.operation_columns == 1 else 2
            place_grid(diagnostic_buttons, tools, diagnostic_columns)

        if layout.operation_columns == 1:
            session_box.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(8, 0))
        else:
            session_box.grid_configure(row=0, column=1, sticky="e", padx=(10, 0), pady=0)

        current_layout = layout

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
                        pause_feedback_pending.clear()
                        publish(worker.snapshot, last_stats)

                    elif command == "resume":
                        pause_requested.clear()
                        pause_feedback_pending.clear()
                        if browser.diagnostic_active:
                            publish_phase("DIAGNOSTIC_MODE", last_stats)
                            continue
                        diagnostic_snapshot = None
                        try:
                            worker.resume()
                        except Exception:
                            pass
                        publish(worker.snapshot, last_stats)

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
                        if (
                            not was_paused
                            and not pause_requested.is_set()
                            and diagnostic_snapshot.state == "JOBS_SYNC_COMPLETED"
                        ):
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
                            if pause_requested.is_set():
                                publish(worker.snapshot, last_stats)
                            else:
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
                            if pause_requested.is_set():
                                publish(worker.snapshot, last_stats)
                                continue
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
                            if pause_requested.is_set():
                                publish(worker.snapshot, last_stats)
                            else:
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
                    0.0
                    if pause_feedback_pending.is_set()
                    else (
                        0.5
                        if snapshot.state not in {"IDLE", "PAUSED", "WAITING_FOR_HUMAN", "JOBS_SYNC_COMPLETED"}
                        else 2.0
                    )
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

                tone = _status_tone(ui)
                bg, border, fg = _STATUS_PALETTES[tone]
                phase.configure(background=bg, highlightbackground=border)
                status_heading_widget.configure(background=bg, foreground=fg)
                status_label_widget.configure(background=bg)

                session_box.configure(background=bg, highlightbackground=border)
                session_heading_widget.configure(background=bg, foreground=fg)
                session_value_widget.configure(background=bg, foreground=fg)

                state = "disabled" if ui.busy else "normal"
                for button in conflict_buttons:
                    button.configure(state=state)

                pause_button.configure(
                    state="disabled" if pause_requested.is_set() else "normal"
                )
                if pause_feedback_pending.is_set():
                    status_var.set("Pausa solicitada · terminando operación actual…")
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
