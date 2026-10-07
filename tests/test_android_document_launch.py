"""Activity launches are dispatched to Android's UI thread without opening any app."""
import sys
import types

from screens import report_screen


def test_document_launch_waits_for_android_ui_dispatch(monkeypatch):
    dispatched, calls = [], []
    def dispatch(function):
        def queued():
            dispatched.append(function)
        return queued
    monkeypatch.setitem(sys.modules, "android", types.ModuleType("android"))
    runnable = types.ModuleType("android.runnable")
    runnable.run_on_ui_thread = dispatch
    monkeypatch.setitem(sys.modules, "android.runnable", runnable)
    activity = types.SimpleNamespace(
        startActivity=lambda intent: calls.append((intent, None)),
        startActivityForResult=lambda intent, code: calls.append((intent, code)),
    )
    report_screen.launch_android_intent(activity, "document-intent", 8474)
    report_screen.launch_android_intent(activity, "view-intent")
    assert calls == []
    for action in dispatched:
        action()
    assert calls == [("document-intent", 8474), ("view-intent", None)]


def test_android_launch_failure_returns_to_kivy_thread(monkeypatch):
    dispatched, scheduled, failures = [], [], []
    runnable = types.ModuleType("android.runnable")
    runnable.run_on_ui_thread = lambda function: lambda: dispatched.append(function)
    monkeypatch.setitem(sys.modules, "android", types.ModuleType("android"))
    monkeypatch.setitem(sys.modules, "android.runnable", runnable)
    monkeypatch.setattr(report_screen.Clock, "schedule_once", lambda callback, _dt: scheduled.append(callback))
    def fail(_intent):
        raise RuntimeError("No installed document viewer")
    report_screen.launch_android_intent(types.SimpleNamespace(startActivity=fail), "intent",
                                       on_error=lambda: failures.append("handled"))
    dispatched[0]()
    assert failures == []
    scheduled[0](0)
    assert failures == ["handled"]
