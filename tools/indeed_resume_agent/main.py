from __future__ import annotations

from collections.abc import Callable

from .api_client import AgentApiClient
from .browser import IndeedBrowser
from .config import load_config
from .credential_store import (
    AgentCredentialMissing,
    read_agent_token,
    write_agent_token,
)
from .ui import run_ui
from .worker import ResumeWorker


def _prompt_for_agent_token() -> str:
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        raw = simpledialog.askstring(
            "ASIATI Resume Agent",
            "Pegue el token de maquina del ASIATI Resume Agent:",
            show="*",
            parent=root,
        )
        value = str(raw or "").strip()
        if len(value) < 32:
            messagebox.showerror(
                "ASIATI Resume Agent",
                "Token invalido. Solicite una credencial nueva al administrador.",
                parent=root,
            )
            return ""
        return value
    finally:
        root.destroy()


def resolve_agent_token(
    *,
    reader: Callable[[], str] = read_agent_token,
    writer: Callable[[str], None] = write_agent_token,
    prompt: Callable[[], str] | None = None,
) -> str:
    """Read the machine token or provision it locally on first launch.

    The raw token never leaves the workstation except as the authenticated
    request header sent to the purpose-specific backend endpoints.
    """
    try:
        return reader()
    except AgentCredentialMissing:
        value = str((prompt or _prompt_for_agent_token)() or "").strip()
        if len(value) < 32:
            raise AgentCredentialMissing(
                "No se configuro una credencial valida para ASIATI Resume Agent."
            )
        writer(value)
        return value


def main() -> None:
    config = load_config()
    try:
        token = resolve_agent_token()
    except AgentCredentialMissing:
        return

    api = AgentApiClient(config, token)
    browser = IndeedBrowser(config)
    worker = ResumeWorker(config=config, api=api, browser=browser)
    try:
        run_ui(worker=worker, api=api, browser=browser)
    finally:
        try:
            browser.close()
        finally:
            api.close()


if __name__ == "__main__":
    main()
