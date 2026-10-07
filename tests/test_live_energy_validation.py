import math
import os
from types import MethodType, SimpleNamespace

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

import pytest

from app_state import AppState
from logic.calculations import default_hourly_percentages
from logic.quote_validation import finite_float_or, live_float_or, validate_hourly_profile
from screens.battery_screen import BatteryScreen
from screens.consumption_screen import ConsumptionScreen
from screens.simulation_screen import MDApp, SimulationScreen
from screens.solar_screen import SolarScreen


@pytest.mark.parametrize("text", [".", "NaN", "inf", "9" * 1000, "invalid"])
def test_live_nonblank_invalid_number_stays_invalid_instead_of_using_default(text):
    assert math.isnan(live_float_or(text, 4.5))
    assert finite_float_or(text, 4.5) == 4.5


@pytest.mark.parametrize("text", ["", "   ", None])
def test_blank_live_number_uses_the_declared_default(text):
    assert live_float_or(text, 4.5) == 4.5


@pytest.mark.parametrize("screen", [SolarScreen, BatteryScreen, SimulationScreen])
def test_live_energy_screen_reader_does_not_hide_nonfinite_input(screen):
    assert math.isnan(screen._float(None, SimpleNamespace(text="9" * 1000), 80))


def test_overflowing_live_solar_field_makes_design_unavailable(monkeypatch):
    state = AppState()
    state.project.monthly_kwh = 120
    monkeypatch.setattr(MDApp, "get_running_app", staticmethod(lambda: SimpleNamespace(state=state)))
    solar = SimpleNamespace(peak_sun_hours_field=SimpleNamespace(text="9" * 1000),
                            efficiency_field=SimpleNamespace(text="80"))
    solar._float = MethodType(SolarScreen._float, solar)
    design = SolarScreen._design(solar)
    assert not design.feasible and design.error
    assert math.isnan(state.peak_sun_hours)


def test_overflowing_live_battery_field_makes_design_unavailable(monkeypatch):
    state = AppState()
    state.project.monthly_kwh = 120
    monkeypatch.setattr(MDApp, "get_running_app", staticmethod(lambda: SimpleNamespace(state=state)))
    battery = SimpleNamespace(dod_field=SimpleNamespace(text="9" * 1000),
                              efficiency_field=SimpleNamespace(text="90"))
    battery._float = MethodType(BatteryScreen._float, battery)
    design = BatteryScreen._design(battery)
    assert not design.feasible and design.error
    assert math.isnan(state.battery_dod_pct)


def test_invalid_live_hourly_field_is_rejected_and_never_drawn_as_nonfinite_data():
    chart_calls = []
    fields = SimpleNamespace(_updating=False, hourly_pct=default_hourly_percentages(70),
                             monthly_kwh=120, _kwh_labels=[SimpleNamespace(text="") for _ in range(24)],
                             total_pct_label=SimpleNamespace(text=""),
                             chart=SimpleNamespace(set_data=lambda *args: chart_calls.append(args)),
                             _refresh_summary=lambda: None)
    fields._refresh_kwh_column = MethodType(ConsumptionScreen._refresh_kwh_column, fields)
    ConsumptionScreen._on_pct_changed(fields, 0, "9" * 1000)
    assert validate_hourly_profile(fields.hourly_pct)
    assert chart_calls == [([], [], [])]
    assert all(label.text == "N/A" for label in fields._kwh_labels)
