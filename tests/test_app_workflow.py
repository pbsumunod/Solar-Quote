"""Exercise the real desktop screen/state/database integration without network I/O."""
import json
import math
import os
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

import pytest
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window

from db import database
from main import SolarClientFinderApp
from screens.client_screen import QUOTE_STEP_SCREENS


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    monkeypatch.setattr("internet_time.init", lambda **_kwargs: None)
    monkeypatch.setattr("logic.site_resources.urlopen", lambda *_args, **_kwargs: pytest.fail("Unexpected site-resource network request"))
    apps = []
    def create(directory=None):
        folder = Path(directory or tmp_path / f"app-{len(apps)}")
        folder.mkdir(parents=True, exist_ok=True)
        app = SolarClientFinderApp()
        app._user_data_dir = str(folder)
        app.root = app.build()
        Clock.unschedule(app._build_app_screens)
        app._show_onboarding = False
        app._screen_manager.transition.duration = 0
        app._build_app_screens(0)
        Window.hide()
        apps.append(app)
        return app
    yield create
    for app in reversed(apps):
        App._running_app = app
        database.configure(app.user_data_dir)
        for screen in app._screen_manager.screens:
            if getattr(screen, "_dialog", None):
                screen._dialog.dismiss()
        app.root.get_screen("simulation").on_leave()
        app.on_stop()
    App._running_app = None
    Window.hide()


@pytest.fixture
def app(make_app):
    return make_app()


def enter_quote(app, monthly=120, name="Test Installer Client"):
    client = app.root.get_screen("client")
    client.client_name_field.text = name
    client.monthly_kwh_field.text = str(monthly)
    client._go_next()
    for name in QUOTE_STEP_SCREENS:
        screen = app.root.get_screen(name)
        screen.on_pre_enter()
        if name == "simulation":
            screen.on_leave()
    return client


def refresh_from_consumption(app):
    for name in QUOTE_STEP_SCREENS[1:]:
        screen = app.root.get_screen(name)
        screen.on_pre_enter()
        if name == "simulation":
            screen.on_leave()


def test_small_quote_selects_one_kw_and_compatible_24v_battery(app):
    enter_quote(app)
    design = app.state.design
    assert design.feasible
    assert design.inverter_rated_kw == 1
    assert design.battery_voltage_class == "24 V"
    assert design.battery_total_kwh >= design.battery_required_kwh
    assert app.root.get_screen("system_design").get_report_data()["equipment"]["inverter_rated_kw"] == 1
    assert all(math.isfinite(result.total_grid_purchase_kwh) for result in app.state.scenario_results.values())


def test_custom_night_profile_increases_selected_battery_and_summary(app):
    enter_quote(app)
    previous = app.state.design.battery_total_kwh
    consumption = app.root.get_screen("consumption")
    consumption.apply_state({"hourly_pct": [0.5] * 12 + [7.83] * 11 + [7.87]})
    refresh_from_consumption(app)
    assert app.state.design.battery_total_kwh > previous
    report = consumption.get_report_data()
    assert report["night_kwh"] == pytest.approx(sum(report["hourly_kwh"][12:]))
    assert report["night_kwh"] > report["day_kwh"]


def test_no_storage_uses_zero_battery_and_no_battery_flow(app):
    client = app.root.get_screen("client")
    client.storage_checkbox.active = False
    enter_quote(app)
    assert app.state.design.feasible
    assert app.state.design.battery_total_kwh == 0
    assert app.state.design.battery_module_count == 0
    for result in app.state.scenario_results.values():
        assert result.total_battery_charge_kwh == 0
        assert result.total_battery_discharge_kwh == 0
        assert all(hour.soc_end_kwh == 0 for hour in result.hours)
    assert client.save_full_quote()


def test_save_restore_keeps_branding_profile_and_site_inputs_then_new_clears(app):
    client = enter_quote(app)
    report = app.root.get_screen("report")
    report.company_name_field.text = "Muñoz – 太阳能"
    client.latitude_field.text = "14.6"
    client.longitude_field.text = "120.98"
    client.shading_field.text = "12"
    assert client.save_full_quote()
    pid = client.current_project_id
    saved = client._collect_quote_data()
    client._new_project()
    assert report.company_name_field.text == ""
    client._load_project(pid)
    assert report.company_name_field.text == "Muñoz – 太阳能"
    assert client._collect_quote_data() == saved
    assert app.state.project.site_shading_pct == 12
    assert app.state.design.feasible
    client._new_project()
    assert report.company_name_field.text == ""
    assert client.current_project_id is None


def test_dirty_project_switch_waits_for_explicit_discard(app):
    client = enter_quote(app)
    assert client.save_full_quote()
    first = client.current_project_id
    client._new_project()
    enter_quote(app, name="Second client")
    assert client.save_full_quote()
    second = client.current_project_id
    client.client_name_field.text = "Unsaved changes"
    client._select_project(first)
    assert client.current_project_id == second
    assert client.client_name_field.text == "Unsaved changes"
    assert client._dialog.title == "Unsaved changes"
    button = next(button for button in client._dialog.buttons if button.text == "DISCARD")
    button.dispatch("on_release")
    assert client.current_project_id == first
    assert client.client_name_field.text == "Test Installer Client"


def test_incomplete_draft_recovers_after_new_app_start(make_app, tmp_path):
    folder = tmp_path / "restart"
    first = make_app(folder)
    client = first.root.get_screen("client")
    client.client_name_field.text = "Recover my incomplete quote"
    client.monthly_kwh_field.text = "."
    first.root.get_screen("report").company_name_field.text = "Draft brand"
    first.on_pause()
    draft = database.load_draft()
    assert draft["raw_fields"]["client"]["monthly_kwh_field"] == "."
    assert database.count_projects() == 0
    first.on_stop()
    second = make_app(folder)
    recovered = second.root.get_screen("client")
    assert recovered.client_name_field.text == "Recover my incomplete quote"
    assert recovered.monthly_kwh_field.text == "."
    assert second.root.get_screen("report").company_name_field.text == "Draft brand"
    assert database.count_projects() == 0


def test_preview_refreshes_after_actual_project_change(app):
    client = enter_quote(app, name="Client A")
    assert client.save_full_quote()
    pid = client.current_project_id
    report = app.root.get_screen("report")
    report.on_pre_enter()
    assert "Client A" in report.preview_label.text
    client._new_project()
    enter_quote(app, name="Client B")
    report.on_pre_enter()
    assert "Client B" in report.preview_label.text
    assert "Client A" not in report.preview_label.text
    client._load_project(pid)
    report.on_pre_enter()
    assert "Client A" in report.preview_label.text
    assert "Client B" not in report.preview_label.text


def test_out_of_range_financial_input_clears_projection_and_blocks_export(app):
    enter_quote(app)
    roi = app.root.get_screen("roi")
    assert roi._last_rows
    roi.inflation_field.text = "99999999999999999999999999"
    assert roi._calculation_error
    assert roi._last_rows == []
    assert roi.net_benefit_label.text == "N/A"
    with pytest.raises(ValueError, match="Inflation"):
        roi.get_report_data()
    roi.inflation_field.text = "3"
    assert roi._calculation_error is None
    assert roi._last_rows


def test_malformed_report_state_from_backup_does_not_crash_project_selection(app):
    client = enter_quote(app)
    assert client.save_full_quote()
    pid = client.current_project_id
    row = dict(database.get_project(pid))
    quote = json.loads(row["quote_data"])
    quote["report"] = []
    row["quote_data"] = json.dumps(quote)
    database.update_project(pid, row)
    client._load_project(pid)
    assert app.root.get_screen("report").company_name_field.text == ""
