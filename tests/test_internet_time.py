from datetime import datetime, timezone

import internet_time


def test_network_time_advances_across_utc_midnight(monkeypatch):
    monkeypatch.setattr(internet_time, "_anchor_utc", datetime(2026, 10, 6, 23, 59, tzinfo=timezone.utc))
    monkeypatch.setattr(internet_time, "_anchor_monotonic", 100)
    monkeypatch.setattr(internet_time.time, "monotonic", lambda: 220)
    assert internet_time.today().isoformat() == "2026-10-07"


def test_failed_startup_fetch_can_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(internet_time, "_anchor_utc", None)
    monkeypatch.setattr(internet_time, "_fetch_in_progress", False)
    monkeypatch.setattr(internet_time, "_last_attempt", 100)
    monkeypatch.setattr(internet_time.time, "monotonic", lambda: 161)
    class Thread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            calls.append(self.target)
    monkeypatch.setattr(internet_time.threading, "Thread", Thread)
    internet_time.init()
    assert calls == [internet_time._fetch]
