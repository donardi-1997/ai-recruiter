from __future__ import annotations

from .api_client import AgentApiClient
from .browser import IndeedBrowser
from .config import load_config
from .credential_store import read_agent_token
from .ui import run_ui
from .worker import ResumeWorker


def main() -> None:
    config = load_config()
    token = read_agent_token()
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
