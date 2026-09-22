from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass

from .api_client import QueueStats
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


_SAFE_HUMAN_CODE = re.compile(r"^(?:INDEED|RESUME)_[A-Z0-9_]{2,100}$")


def build_ui_state(snapshot: WorkerSnapshot, stats: QueueStats) -> UiState:
    state = snapshot.state
    session = "Needs attention" if state in {
        "WAITING_FOR_HUMAN",
        "LEASE_LOST",
        "FAILED",
        "FULL_SYNC_ATTENTION",
        "SYNC_FAILED",
    } else "Ready"
    labels = {
        "IDLE": "Esperando tareas",
        "DOWNLOADING": "Descargando CV...",
        "COMPLETED": "CV cargado correctamente",
        "PAUSED": "En pausa",
        "BROWSER_READY": "Chrome está abierto con el perfil del agente. Inicia sesión o resuelve la verificación, mantén Chrome abierto y luego pulsa Resume",
        "MANUAL_BROWSER_OPEN": "Chrome está abierto con el perfil persistente del agente",
        "MANUAL_LOGIN_REQUIRED": "Indeed requiere verificación. Pulsa Open Indeed (Google Chrome), inicia sesión o resuelve el CAPTCHA y luego pulsa Resume",
        "MANUAL_OPEN_FAILED": "No se pudo abrir Google Chrome con el perfil del agente",
        "DIAGNOSTIC_ANCHOR_FAILED": "Chrome no creó la pestaña de respaldo. Cierra Chrome y vuelve a abrir Diagnostic mode",
        "DIAGNOSTIC_MODE": "Modo diagnóstico activo: usa Indeed normalmente y luego pulsa Guardar diagnóstico",
        "DIAGNOSTIC_SAVED": "Diagnóstico guardado",
        "DIAGNOSTIC_BROWSER_FAILED": "No se pudo recuperar la sesión de Chrome del agente. Pulsa Open Indeed (Google Chrome) y vuelve a intentar Diagnostic mode",
        "WAITING_FOR_HUMAN": "Indeed requiere intervención manual",
        "NEEDS_REVIEW_CONTINUE": "Caso apartado para revisión manual; continuando con la cola",
        "LEASE_LOST": "La tarea será reclamada de forma segura",
        "RETRY": "Reintento programado",
        "FAILED": "La tarea requiere revisión",
        "STOPPED": "Detenido",
        "ERROR": "Error de conexión con el servicio",
        "SYNCING": "Revisando todas las vacantes y candidatos de Indeed...",
        "SYNC_READY": "Fuentes sincronizadas. Procesando la cola completa de CV...",
        "FULL_SYNC_COMPLETED": "Sincronización completa",
        "FULL_SYNC_ATTENTION": "Sincronización completada con casos por revisar",
        "SYNC_FAILED": "No fue posible preparar la sincronización completa",
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
    if state == "DIAGNOSTIC_SAVED" and snapshot.last_error:
        status_label = snapshot.last_error
    if state in {"SYNC_READY", "FULL_SYNC_COMPLETED", "FULL_SYNC_ATTENTION"} and snapshot.last_error:
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
    )


def run_ui(*, worker, api, browser) -> None:
    import tkinter as tk
    from tkinter import ttk

    # Production safety: never claim a task until the operator explicitly
    # finishes the manual Indeed session and presses Resume.
    worker.pause()

    root = tk.Tk()
    root.title("ASIATI Resume Agent")
    root.geometry("760x470")
    root.minsize(700, 430)

    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="ASIATI Resume Agent", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Indeed resume bridge", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 18))

    session_var = tk.StringVar(value="Starting")
    status_var = tk.StringVar(value="Iniciando agente...")
    candidate_var = tk.StringVar(value="-")
    counters = {
        name: tk.StringVar(value="0")
        for name in ("pending", "downloading", "completed", "attention", "retry", "failed")
    }

    session_row = ttk.Frame(frame)
    session_row.pack(fill="x", pady=(0, 14))
    ttk.Label(session_row, text="Indeed session:", font=("Segoe UI", 10, "bold")).pack(side="left")
    ttk.Label(session_row, textvariable=session_var).pack(side="left", padx=(8, 0))

    grid = ttk.Frame(frame)
    grid.pack(fill="x", pady=(0, 14))
    rows = [
        ("Pending", "pending"),
        ("Downloading", "downloading"),
        ("Completed", "completed"),
        ("Needs attention", "attention"),
        ("Retry", "retry"),
        ("Failed", "failed"),
    ]
    for idx, (label, key) in enumerate(rows):
        ttk.Label(grid, text=f"{label}:").grid(row=idx, column=0, sticky="w", pady=2)
        ttk.Label(grid, textvariable=counters[key], font=("Segoe UI", 10, "bold")).grid(row=idx, column=1, sticky="e", padx=(24, 0), pady=2)
    grid.columnconfigure(0, weight=1)

    ttk.Separator(frame).pack(fill="x", pady=(4, 14))
    ttk.Label(frame, text="Current candidate", font=("Segoe UI", 9, "bold")).pack(anchor="w")
    ttk.Label(frame, textvariable=candidate_var, wraplength=450).pack(anchor="w", pady=(2, 10))
    ttk.Label(frame, text="Status", font=("Segoe UI", 9, "bold")).pack(anchor="w")
    ttk.Label(frame, textvariable=status_var, wraplength=450).pack(anchor="w", pady=(2, 18))

    commands: queue.Queue[str] = queue.Queue()
    updates: queue.Queue[UiState] = queue.Queue()
    stop_event = threading.Event()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")

    primary_buttons = ttk.Frame(buttons)
    primary_buttons.pack(fill="x")
    ttk.Button(primary_buttons, text="Pause", command=lambda: commands.put("pause")).pack(side="left")
    ttk.Button(primary_buttons, text="Resume", command=lambda: commands.put("resume")).pack(side="left", padx=8)
    ttk.Button(primary_buttons, text="Retry failed", command=lambda: commands.put("retry_failed")).pack(side="left")
    ttk.Button(primary_buttons, text="Retry attention", command=lambda: commands.put("retry_attention")).pack(side="left", padx=(8, 0))
    ttk.Button(
        primary_buttons,
        text="Sincronizar todo",
        command=lambda: commands.put("sync_all"),
    ).pack(side="left", padx=(8, 0))
    ttk.Button(
        primary_buttons,
        text=f"Open Indeed ({browser.browser_label})",
        command=lambda: commands.put("open"),
    ).pack(side="right")

    diagnostic_buttons = ttk.Frame(buttons)
    diagnostic_buttons.pack(fill="x", pady=(8, 0))
    ttk.Button(
        diagnostic_buttons,
        text="Diagnostic mode",
        command=lambda: commands.put("diagnostic_start"),
    ).pack(side="left")
    ttk.Button(
        diagnostic_buttons,
        text="Guardar diagnóstico",
        command=lambda: commands.put("diagnostic_stop"),
    ).pack(side="left", padx=(8, 0))

    def publish(snapshot: WorkerSnapshot, stats: QueueStats) -> None:
        updates.put(build_ui_state(snapshot, stats))

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
                            diagnostic_snapshot = WorkerSnapshot(
                                "DIAGNOSTIC_MODE",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                            publish(diagnostic_snapshot, last_stats)
                            continue
                        diagnostic_snapshot = None
                        if browser.manual_session_open:
                            publish(
                                WorkerSnapshot(
                                    "MANUAL_BROWSER_OPEN",
                                    worker.snapshot.active_candidate,
                                    worker.snapshot.processed_session,
                                    None,
                                ),
                                last_stats,
                            )
                        else:
                            try:
                                worker.resume()
                            except Exception:
                                pass
                    elif command == "sync_all":
                        if browser.diagnostic_active:
                            continue
                        diagnostic_snapshot = None
                        worker.pause()
                        syncing = WorkerSnapshot(
                            "SYNCING",
                            worker.snapshot.active_candidate,
                            worker.snapshot.processed_session,
                            None,
                        )
                        publish(syncing, last_stats)
                        try:
                            result = api.sync_all()
                            last_stats = api.stats()
                            full_sync_active = True
                            full_sync_provider_pending = result.reconcile_provider_pending
                            detail = (
                                f"Revisión preparada: {result.reconcile_jobs} vacantes, "
                                f"{result.reconcile_scanned} candidatos Indeed y "
                                f"{result.discovered} mensajes auditados; "
                                f"{result.created + result.reconcile_queued} tareas nuevas. "
                                f"Cola pendiente: {last_stats.pending}."
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
                        except Exception:
                            full_sync_active = False
                            diagnostic_snapshot = WorkerSnapshot(
                                "SYNC_FAILED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
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
                            error_code = str(exc)
                            if error_code == "INDEED_MANUAL_BROWSER_OPEN":
                                state = "MANUAL_BROWSER_OPEN"
                            elif error_code == "INDEED_MANUAL_LOGIN_REQUIRED":
                                state = "MANUAL_LOGIN_REQUIRED"
                            elif error_code == "INDEED_DIAGNOSTIC_ANCHOR_FAILED":
                                state = "DIAGNOSTIC_ANCHOR_FAILED"
                            else:
                                state = "ERROR"
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
                            path = None
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
                        publish(worker.snapshot, last_stats)
                        if browser.diagnostic_active:
                            try:
                                browser.stop_diagnostic()
                            except Exception:
                                pass
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
                    except RuntimeError as exc:
                        error_code = str(exc)
                        if error_code == "INDEED_MANUAL_LOGIN_REQUIRED":
                            try:
                                browser.open_indeed()
                            except Exception:
                                pass
                            diagnostic_snapshot = WorkerSnapshot(
                                "MANUAL_LOGIN_REQUIRED",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        else:
                            diagnostic_snapshot = WorkerSnapshot(
                                "ERROR",
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
                elif browser.manual_session_open:
                    snapshot = WorkerSnapshot(
                        "MANUAL_BROWSER_OPEN",
                        worker.snapshot.active_candidate,
                        worker.snapshot.processed_session,
                        None,
                    )
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
                                    "Revisión masiva terminada con pendientes: "
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
                                    "Prueba final completada: la cola está en cero y "
                                    f"{last_stats.completed} CV de Indeed figuran completados."
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
                        publish(WorkerSnapshot("ERROR", None, worker.snapshot.processed_session, None), last_stats)
                        snapshot = worker.snapshot

                delay = 0.5 if snapshot.state not in {"IDLE", "PAUSED", "WAITING_FOR_HUMAN"} else 2.0
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
