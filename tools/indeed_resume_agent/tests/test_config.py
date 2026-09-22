import pytest

from tools.indeed_resume_agent.config import load_config


def test_default_profile_is_isolated_under_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ASIATI_RESUME_AGENT_API_BASE_URL", raising=False)
    cfg = load_config()
    assert cfg.browser_name == "chrome"
    assert cfg.browser_profile_dir == tmp_path / "ASIATI" / "ResumeAgent" / "browser-profile-chrome"
    assert cfg.api_base_url == "https://dzcwl3yhv133t.cloudfront.net"
    assert cfg.diagnostic_screenshots is False


def test_api_base_url_is_https_and_has_no_trailing_slash(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_API_BASE_URL", "https://example.test/")
    assert load_config().api_base_url == "https://example.test"


@pytest.mark.parametrize("url", ["http://example.com", "ftp://example.com", "example.com"])
def test_rejects_non_https_remote_api_url(tmp_path, monkeypatch, url):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_API_BASE_URL", url)
    with pytest.raises(ValueError, match="HTTPS"):
        load_config()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/", "http://localhost:8000/"])
def test_allows_loopback_http_for_development(tmp_path, monkeypatch, url):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_API_BASE_URL", url)
    assert load_config().api_base_url == url.rstrip("/")


def test_edge_can_be_selected_with_isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_BROWSER", "edge")
    cfg = load_config()
    assert cfg.browser_name == "edge"
    assert cfg.browser_profile_dir == tmp_path / "ASIATI" / "ResumeAgent" / "browser-profile-edge"


def test_browser_profile_override_wins_over_browser_specific_default(tmp_path, monkeypatch):
    explicit = tmp_path / "custom-profile"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_BROWSER", "chrome")
    monkeypatch.setenv("ASIATI_RESUME_AGENT_BROWSER_PROFILE_DIR", str(explicit))
    assert load_config().browser_profile_dir == explicit


def test_rejects_unknown_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_BROWSER", "firefox")
    with pytest.raises(ValueError, match="chrome, edge"):
        load_config()


def test_diagnostic_screenshots_require_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_DIAGNOSTIC_SCREENSHOTS", "true")

    assert load_config().diagnostic_screenshots is True


def test_rejects_invalid_diagnostic_screenshot_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ASIATI_RESUME_AGENT_DIAGNOSTIC_SCREENSHOTS", "maybe")

    with pytest.raises(ValueError, match="boolean"):
        load_config()
