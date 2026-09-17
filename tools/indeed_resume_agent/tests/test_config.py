import pytest

from tools.indeed_resume_agent.config import load_config


def test_default_profile_is_isolated_under_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ASIATI_RESUME_AGENT_API_BASE_URL", raising=False)
    cfg = load_config()
    assert cfg.browser_profile_dir == tmp_path / "ASIATI" / "ResumeAgent" / "browser-profile"
    assert cfg.api_base_url == "https://dzcwl3yhv133t.cloudfront.net"


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
