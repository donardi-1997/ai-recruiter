from __future__ import annotations

import queue
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


def build_ui_state(snapshot: WorkerSnapshot, stats: QueueStats) -> UiState:
    state = snapshot.state
    session = "Needs attention" if state in {"WAITING_FOR_HUMAN", "LEASE_LOST", "FAILED"} else "Ready"
    labels = {
        "IDLE": "Esperando tareas",
        "DOWNLOADING": "Descargando CV...",
        "COMPLETED": "CV cargado correctamente",
        "PAUSED": "En pausa",
        "MANUAL_BROWSER_OPEN": "Cierra el navegador manual para continuar",
        "MANUAL_LOGIN_REQUIRED": "Inicia sesión primero con Open Indeed (Google Chrome), cierra Chrome y vuelve a intentar",
        "DIAGNOSTIC_MODE": "Modo diagnóstico activo: usa Indeed normalmente y luego pulsa Guardar diagnóstico",
        "DIAGNOSTIC_SAVED": "Diagnóstico guardado",
        "WAITING_FOR_HUMAN": "Indeed requiere intervención manual",
        "LEASE_LOST": "La tarea será reclamada de forma segura",
        "RETRY": "Reintento programado",
        "FAILED": "La tarea requiere revisión",
        "STOPPED": "Detenido",
        "ERROR": "Error de conexión con el servicio",
    }
    status_label = labels.get(state, "Procesando")
    diagnostic_prefix = "Indeed mostró una interfaz no reconocida. Diagnóstico local:"
    if (
        state == "WAITING_FOR_HUMAN"
        and snapshot.last_error
        and snapshot.last_error.startswith(diagnostic_prefix)
    ):
        status_label = snapshot.last_error
    if state == "DIAGNOSTIC_SAVED" and snapshot.last_error:
        status_label = snapshot.last_error

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
                        if browser.manual_session_open:
                            diagnostic_snapshot = WorkerSnapshot(
                                "MANUAL_BROWSER_OPEN",
                                worker.snapshot.active_candidate,
                                worker.snapshot.processed_session,
                                None,
                            )
                        else:
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
                                    "ERROR",
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
                        if browser.diagnostic_active:
                            continue
                        diagnostic_snapshot = None
                        worker.pause()
                        publish(worker.snapshot, last_stats)
                        try:
                            browser.open_indeed()
                        except Exception:
                            pass

                if browser.diagnostic_active:
                    try:
                        browser.poll_diagnostic()
                    except Exception:
                        pass
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
