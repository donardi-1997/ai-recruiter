from tools.indeed_resume_agent.browser_use_driver import (
    INDEED_JOBS_URL,
    _job_key_from_url,
)


def test_jobs_workspace_uses_approved_open_and_paused_url():
    assert INDEED_JOBS_URL == (
        "https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false&"
        "createdOnIndeed=true&tab=0&sortDirection=DESC&sortField=datePostedOnIndeed"
    )


def test_job_key_parser_accepts_common_employer_url_shapes():
    assert _job_key_from_url("https://employers.indeed.com/jobs/view?id=ABC123") == "ABC123"
    assert _job_key_from_url("https://employers.indeed.com/jobs/view?jobId=job-456") == "job-456"
    assert _job_key_from_url("https://employers.indeed.com/jobs/job-789") == "job-789"


def test_job_key_parser_fails_closed_without_stable_identity():
    assert _job_key_from_url("https://employers.indeed.com/jobs") == ""
    assert _job_key_from_url("https://evil.example/jobs/view?id=secret") == ""
