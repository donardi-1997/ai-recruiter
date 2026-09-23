from __future__ import annotations

from collections.abc import Callable

from .api_client import AgentApiClient
from .browser_use_driver import IndeedBrowserUse
from .config import load_config
from .credential_store import (
    AgentCredentialMissing,
    read_agent_token,
    write_agent_token,
)
from .download_capture_compat import install_download_capture_compat
from .indeed_candidates_current import install_current_indeed_candidates
from .indeed_jobs_current import install_current_indeed_jobs
from .jobs_listing_compat import install_jobs_listing_compat
from .runtime_compat import install_runtime_compat
from .ui_v3 import run_ui
from .vacancy_click_recovery import install_vacancy_click_recovery
from .vacancy_pipeline import install_resilient_vacancy_pipeline
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
    browser = IndeedBrowserUse(config)
    install_download_capture_compat(browser)
    install_runtime_compat(browser)
    install_jobs_listing_compat()
    install_vacancy_click_recovery()
    # Install the production DOM contracts last. Older shims remain available
    # as regression/fallback code but cannot override the stable identities,
    # structural auth, or pagination used by current Indeed.
    install_current_indeed_jobs(browser)
    # The current Indeed DOM collector is wrapped by a two-phase pipeline that
    # never throws away valid hydrated vacancies only because the list counter
    # and traversed rows differ. Authentication and zero usable details still
    # fail closed.
    install_resilient_vacancy_pipeline()
    install_current_indeed_candidates(browser)
    worker = ResumeWorker(
        config=config,
        api=api,
        browser=browser,
        start_paused=True,
    )
    try:
        run_ui(worker=worker, api=api, browser=browser)
    finally:
        try:
            browser.close()
        finally:
            api.close()


if __name__ == "__main__":
    main()
