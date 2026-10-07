"""Exercise the real screen calculation APIs without constructing UI widgets."""

import os
from types import MethodType, SimpleNamespace

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

import pytest

from app_state import AppState
from logic.calculations import default_hourly_percentages
from logic.equipment import refresh_equipment_design
from logic.financial import build_projection_table, projection_sensitivity
from logic.quote_validation import finite_float_or
from logic.site_resources import MONTH_DAYS
from screens.roi_screen import RoiScreen
from screens.simulation_screen import MDApp, SimulationScreen
from screens.solar_screen import SolarScreen


@pytest.fixture
def energy_views(monkeypatch):
    state = AppState()
    state.project.monthly_kwh = 120
    state.hourly_pct = default_hourly_percentages(70)
    state.resource_is_all_sky = True
    state.monthly_peak_sun_hours = [4.5] * 12
    state.peak_sun_hours = 4.5
    state.resource_source = "NASA POWER roof estimate"
    refresh_equipment_design(state)
    simulation = SimpleNamespace(export_checkbox=SimpleNamespace(active=True), harvest_pct=state.harvest_pct)
    simulation._sync_inputs = MethodType(SimulationScreen._sync_inputs, simulation)
    calls = []
    def run(factor, **kwargs):
        calls.append((factor, kwargs))
        return SimulationScreen._run_for_factor(simulation, factor, **kwargs)
    simulation._run_for_factor = run
    app = SimpleNamespace(state=state, root=SimpleNamespace(get_screen=lambda _name: simulation))
    monkeypatch.setattr(MDApp, "get_running_app", staticmethod(lambda: app))
    scenarios = {name: run(factor) for name, factor in state.weather_factors.items()}
    state.scenario_results = scenarios
    state.export_enabled = state.design.supports_grid_export
    view = SimpleNamespace(_annual_cache_key=None, _annual_energy={}, scenario_results=scenarios,
                           monthly_kwh=state.project.monthly_kwh,
                           _weather_mix_pct=lambda: dict(state.weather_mix))
    calls.clear()
    return state, simulation, view, calls


def test_all_sky_monthly_annualization_calibrates_once_and_reuses_complete_cache(energy_views):
    state, _simulation, view, calls = energy_views
    first = RoiScreen._annual_figures(view)
    assert len(calls) == 36
    expected = state.solar_total_kw * 4.5 * state.efficiency_pct / 100 * 365
    assert view._annual_energy["total_solar_kwh"] == pytest.approx(expected)
    assert RoiScreen._annual_figures(view) == pytest.approx(first)
    assert len(calls) == 36


def test_manual_then_same_all_sky_resource_does_not_reuse_overwritten_cache(energy_views):
    state, _simulation, view, calls = energy_views
    expected = RoiScreen._annual_figures(view)
    state.resource_is_all_sky = False
    RoiScreen._annual_figures(view)
    state.resource_is_all_sky = True
    assert RoiScreen._annual_figures(view) == pytest.approx(expected)
    assert len(calls) == 72


def test_monthly_solar_production_is_weighted_by_actual_month_lengths(energy_views):
    state, _simulation, view, _calls = energy_views
    state.monthly_peak_sun_hours = [3] * 6 + [6] * 6
    state.peak_sun_hours = sum(v * days for v, days in zip(state.monthly_peak_sun_hours, MONTH_DAYS)) / 365
    refresh_equipment_design(state)
    RoiScreen._annual_figures(view)
    expected = state.solar_total_kw * state.efficiency_pct / 100 * sum(
        v * days for v, days in zip(state.monthly_peak_sun_hours, MONTH_DAYS))
    assert view._annual_energy["total_solar_kwh"] == pytest.approx(expected)


def test_weather_mix_change_recalibrates_without_double_derating_all_sky_resource(energy_views):
    state, _simulation, view, calls = energy_views
    RoiScreen._annual_figures(view)
    expected_per_kw = view._annual_energy["total_solar_kwh"] / state.solar_total_kw
    state.weather_mix = {"Sunny": 80, "Cloudy": 15, "Rainy": 5}
    RoiScreen._annual_figures(view)
    # Auto selection can change conversion efficiency/array size as sunny peak
    # changes; the all-sky energy resource per installed kWp must remain fixed.
    assert view._annual_energy["total_solar_kwh"] / state.solar_total_kw == pytest.approx(expected_per_kw)
    assert len(calls) == 72


def test_zero_weather_output_with_manual_resource_has_no_energy_savings(energy_views):
    state, simulation, view, _calls = energy_views
    state.resource_is_all_sky = False
    state.weather_factors = dict.fromkeys(state.weather_factors, 0)
    view.scenario_results = {name: simulation._run_for_factor(0) for name in state.weather_factors}
    purchase, export = RoiScreen._annual_figures(view)
    assert purchase == pytest.approx(state.project.monthly_kwh * 12)
    assert export == 0


def test_all_sky_with_zero_blended_weather_output_is_rejected(energy_views):
    state, _simulation, view, _calls = energy_views
    state.weather_factors = dict.fromkeys(state.weather_factors, 0)
    with pytest.raises(ValueError, match="zero weather"):
        RoiScreen._annual_figures(view)


def test_failed_manual_simulation_cannot_be_interpreted_as_zero_grid_purchase(energy_views):
    state, _simulation, view, _calls = energy_views
    state.resource_is_all_sky = False
    view.scenario_results = {}
    with pytest.raises(ValueError):
        RoiScreen._annual_figures(view)


def test_zero_cost_sensitivity_has_undefined_roi_and_finite_cash_flow():
    inputs = dict(system_cost=0, base_rate=14.5, inflation_pct=3, annual_kwh_without_solar=1440,
                  annual_grid_purchase_kwh=600, annual_grid_export_kwh=0, export_rate=6,
                  export_enabled=False, maintenance_method="percentage", maintenance_pct=1,
                  maintenance_fixed=0, maintenance_inflation_pct=0, years=25, discount_rate_pct=6)
    rows = build_projection_table(**inputs)
    assert rows[-1].cumulative_discounted_cash_flow > 0
    assert all(case["roi_pct"] is None and case["payback_years"] is None
               for case in projection_sensitivity(**inputs))


def test_no_battery_projection_ignores_old_battery_replacement_assumptions(energy_views):
    state, _simulation, view, _calls = energy_views
    state.project.storage_enabled = False
    refresh_equipment_design(state)
    view.monthly_kwh, view.electricity_rate = 120, 14.5
    view.export_enabled, view.maintenance_method = True, "percentage"
    view._system_cost = lambda: 10000
    view._float = lambda field, default=0: finite_float_or(field.text, default)
    view._int = lambda field, default=1: int(field.text)
    view._projection_options = lambda: dict(battery_degradation_pct=2, battery_replacement_years=10,
                                           battery_replacement_cost=5000)
    view._effective_projection_options = MethodType(RoiScreen._effective_projection_options, view)
    for name, text in (("inflation_field", "3"), ("export_rate_field", "6"),
                       ("maintenance_pct_field", "1"), ("maintenance_fixed_field", "0"),
                       ("maintenance_inflation_field", "0"), ("years_field", "25")):
        setattr(view, name, SimpleNamespace(text=text))
    inputs = RoiScreen._projection_inputs(view, 600, 0)
    assert inputs.get("battery_replacement_years", 0) == 0
    assert inputs.get("battery_replacement_cost", 0) == 0
    assert all(row.replacement == 0 for row in build_projection_table(**inputs))


def test_solar_screen_clears_resource_when_client_changes_roof_geometry(energy_views):
    state, _simulation, _view, _calls = energy_views
    state.project.site_latitude, state.project.site_longitude = 14.6, 121
    state.resource_metadata = dict(latitude=14.6, longitude=121, tilt_deg=10,
                                   azimuth_deg=180, shading_pct=0)
    state.resource_coordinates = (14.6, 121)
    state.project.site_tilt_deg = 25
    solar = SimpleNamespace(_applying_state=False, peak_sun_hours_field=SimpleNamespace(text="5.25"),
                            _recalculate=lambda: None)
    solar._clear_resource = MethodType(SolarScreen._clear_resource, solar)
    SolarScreen.on_pre_enter(solar)
    assert not state.resource_is_all_sky
    assert state.monthly_peak_sun_hours == []
    assert state.resource_metadata == {}
    assert state.resource_coordinates is None
    assert float(solar.peak_sun_hours_field.text) == state.peak_sun_hours == 4.5
    assert "Site or roof inputs changed" in state.resource_warning


def test_solar_screen_restore_normalizes_malformed_resource_for_live_roi(energy_views):
    state, _simulation, _view, _calls = energy_views
    solar = SimpleNamespace(_applying_state=False, peak_sun_hours_field=SimpleNamespace(text=""),
                            efficiency_field=SimpleNamespace(text=""), _recalculate=lambda: None)
    SolarScreen.apply_state(solar, dict(peak_sun_hours=5, resource_is_all_sky=True,
                                      monthly_peak_sun_hours="invalid", resource_metadata=123))
    assert not state.resource_is_all_sky
    assert state.monthly_peak_sun_hours == []
    assert state.resource_metadata == {}
    assert float(solar.peak_sun_hours_field.text) == 4.5
