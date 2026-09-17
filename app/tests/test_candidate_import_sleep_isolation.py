"""Regression contract: retry-delay tests must not patch Python's global time module."""

import time

from app.workers import candidate_imports as worker


def test_worker_sleep_hook_can_be_patched_without_replacing_stdlib_sleep(monkeypatch):
    original_sleep = time.sleep
    recorded = []

    monkeypatch.setattr(worker, "_sleep", lambda seconds: recorded.append(seconds))

    worker._sleep(1)

    assert recorded == [1]
    assert time.sleep is original_sleep
