import threading
from types import SimpleNamespace

from screens.report_screen import ReportScreen


def test_export_snapshots_inputs_before_background_work(tmp_path, monkeypatch):
    data = {"client": {"client_name": "Original", "project_date": "2026-10-06"}, "roi": {"system_cost": 100}}
    client = SimpleNamespace(_validate=lambda _project: None, _collect_project=lambda: object(), _collect_quote_data=lambda: {})
    app = SimpleNamespace(user_data_dir=str(tmp_path), root=SimpleNamespace(get_screen=lambda _name: client))
    jobs = []
    screen = SimpleNamespace(_collect_data=lambda: data, _start_export_worker=jobs.append)
    monkeypatch.setattr("screens.report_screen.MDApp.get_running_app", lambda: app)
    monkeypatch.setattr("screens.report_screen.validate_quote_steps", lambda _data: None)
    monkeypatch.setattr("screens.report_screen.database.get_tier", lambda: "pro")
    ReportScreen._do_export(screen, "csv")
    data["client"]["client_name"] = "Edited while exporting"
    data["roi"]["system_cost"] = 999
    assert jobs[0]["data"]["client"]["client_name"] == "Original"
    assert jobs[0]["data"]["roi"]["system_cost"] == 100


def test_generation_runs_off_ui_thread_and_completion_is_scheduled(tmp_path, monkeypatch):
    folder = tmp_path / "charts"
    folder.mkdir()
    scheduled, finished, threads = [], [], []
    ready = threading.Event()
    def generate(*_args, **_kwargs):
        threads.append(threading.current_thread())
    def schedule(callback, _delay):
        scheduled.append(callback)
        ready.set()
    monkeypatch.setattr("screens.report_screen.generate_atomic", generate)
    monkeypatch.setattr("screens.report_screen.Clock.schedule_once", schedule)
    job = {"kind": "csv", "path": str(tmp_path / "quote.csv"), "data": {},
           "tmp_dir": str(folder), "images": {}, "watermark": None}
    screen = SimpleNamespace(_finish_export=lambda job, error: finished.append((job, error)))
    ReportScreen._start_export_worker(screen, job)
    assert ready.wait(5)
    assert threads[0] is not threading.current_thread()
    assert not finished
    scheduled[0](0)
    assert finished == [(job, None)]
    assert not folder.exists()


def test_worker_failure_cleans_capture_folder_and_reports_error(tmp_path, monkeypatch):
    folder = tmp_path / "charts"
    folder.mkdir()
    (folder / "failed.png").write_bytes(b"pixels")
    scheduled = []
    ready = threading.Event()
    def fail(*_args, **_kwargs):
        raise OSError("out of storage")
    def schedule(callback, _delay):
        scheduled.append(callback)
        ready.set()
    monkeypatch.setattr("screens.report_screen.generate_atomic", fail)
    monkeypatch.setattr("screens.report_screen.Clock.schedule_once", schedule)
    errors = []
    screen = SimpleNamespace(_finish_export=lambda _job, error: errors.append(error))
    job = {"kind": "csv", "path": str(tmp_path / "quote.csv"), "data": {},
           "tmp_dir": str(folder), "images": {}, "watermark": None}
    ReportScreen._start_export_worker(screen, job)
    assert ready.wait(5)
    scheduled[0](0)
    assert errors[0]
    assert not folder.exists()


def test_preview_refreshes_when_entering_a_different_project():
    current = {"client_name": "Client A"}
    label = SimpleNamespace(text="Client A")
    screen = SimpleNamespace(preview_label=label, _refresh_preview=lambda: setattr(label, "text", current["client_name"]))
    current["client_name"] = "Client B"
    ReportScreen.on_pre_enter(screen)
    assert label.text == "Client B"
