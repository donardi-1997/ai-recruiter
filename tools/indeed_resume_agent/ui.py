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
        "WAITING_FOR_HUMAN": "Indeed requiere intervención manual",
        "LEASE_LOST": "La tarea será reclamada de forma segura",
        "RETRY": "Reintento programado",
        "FAILED": "La tarea requiere revisión",
        "STOPPED": "Detenido",
        "ERROR": "Error de conexión con el servicio",
    }
    return UiState(
        session_label=session,
        status_label=labels.get(state, "Procesando"),
        pending=max(0, stats.pending),
        downloading=1 if state == "DOWNLOADING" else min(max(stats.claimed, 0), 1),
        completed=max(stats.completed, 0),
        needs_attention=max(stats.needs_human, 0),
        failed=max(stats.failed, 0),
        current_candidate=snapshot.active_candidate or "-",
    )


def run_ui(*, worker, api, browser) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("ASIATI Resume Agent")
    root.geometry("520x430")
    root.minsize(480, 390)

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
    counters = {name: tk.StringVar(value="0") for name in ("pending", "downloading", "completed", "attention", "failed")}

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
    ttk.Button(buttons, text="Pause", command=lambda: commands.put("pause")).pack(side="left")
    ttk.Button(buttons, text="Resume", command=lambda: commands.put("resume")).pack(side="left", padx=8)
    ttk.Button(buttons, text="Open Indeed", command=lambda: commands.put("open")).pack(side="right")

    def publish(snapshot: WorkerSnapshot, stats: QueueStats) -> None:
        updates.put(build_ui_state(snapshot, stats))

    def agent_loop() -> None:
        last_stats = QueueStats(0, 0, 0, 0, 0, 0)
        try:
            browser.start()
            while not stop_event.is_set():
                while True:
                    try:
                        command = commands.get_nowait()
                    except queue.Empty:
                        break
                    if command == "pause":
                        worker.pause()
                    elif command == "resume":
                        try:
                            worker.resume()
                        except Exception:
                            pass
                    elif command == "open":
                        try:
                            browser.open_indeed()
                        except Exception:
                            pass

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
