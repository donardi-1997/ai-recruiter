from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

DEFAULT_API_BASE_URL = "https://dzcwl3yhv133t.cloudfront.net"
DEFAULT_BROWSER = "chrome"
SUPPORTED_BROWSERS = {"chrome", "edge"}


@dataclass(frozen=True)
class AgentConfig:
    api_base_url: str
    browser_profile_dir: Path
    browser_name: str = DEFAULT_BROWSER
    request_timeout_seconds: float = 30.0
    heartbeat_interval_seconds: float = 120.0
    idle_poll_seconds: float = 10.0
    max_pdf_bytes: int = 15 * 1024 * 1024
    diagnostic_screenshots: bool = False


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = str(env.get(key, "")).strip()
    if not raw:
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")
    return value


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = str(env.get(key, "")).strip().casefold()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean")


def _normalize_api_base_url(raw: str) -> str:
    value = str(raw or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return value
    raise ValueError("ASIATI Resume Agent API URL must use HTTPS (except localhost development)")


def load_config(*, environ: Mapping[str, str] | None = None) -> AgentConfig:
    env = os.environ if environ is None else environ
    local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    browser_name = str(
        env.get("ASIATI_RESUME_AGENT_BROWSER", DEFAULT_BROWSER)
    ).strip().casefold()
    if browser_name not in SUPPORTED_BROWSERS:
        raise ValueError(
            "ASIATI_RESUME_AGENT_BROWSER must be one of: chrome, edge"
        )

    profile_override = str(env.get("ASIATI_RESUME_AGENT_BROWSER_PROFILE_DIR", "")).strip()
    profile_dir = (
        Path(profile_override).expanduser()
        if profile_override
        else Path(local_app_data)
        / "ASIATI"
        / "ResumeAgent"
        / f"browser-profile-{browser_name}"
    )
    return AgentConfig(
        api_base_url=_normalize_api_base_url(
            env.get("ASIATI_RESUME_AGENT_API_BASE_URL", DEFAULT_API_BASE_URL)
        ),
        browser_profile_dir=profile_dir,
        browser_name=browser_name,
        request_timeout_seconds=_env_float(
            env, "ASIATI_RESUME_AGENT_REQUEST_TIMEOUT_SECONDS", 30.0
        ),
        heartbeat_interval_seconds=_env_float(
            env, "ASIATI_RESUME_AGENT_HEARTBEAT_INTERVAL_SECONDS", 120.0
        ),
        idle_poll_seconds=_env_float(
            env, "ASIATI_RESUME_AGENT_IDLE_POLL_SECONDS", 10.0
        ),
        diagnostic_screenshots=_env_bool(
            env,
            "ASIATI_RESUME_AGENT_DIAGNOSTIC_SCREENSHOTS",
            False,
        ),
    )
