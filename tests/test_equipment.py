import pytest

from app_state import AppState
from logic.calculations import default_hourly_percentages, daily_consumption_kwh
from logic.equipment import (
    BATTERY_CATALOG, INVERTER_CATALOG, calibrated_peak_sun_hours,
    refresh_equipment_design, select_equipment_design,
)


def _design(monthly=300, **kwargs):
    return select_equipment_design(monthly, default_hourly_percentages(70), 4.5, 80, **kwargs)


def test_catalog_contains_small_residential_and_high_voltage_tiers():
    assert {1, 3, 5, 6, 8, 10, 12, 16, 18, 20, 25, 30, 40, 50} <= {s.rated_kw for s in INVERTER_CATALOG}
    assert all(s.sources for s in INVERTER_CATALOG)


def test_small_client_gets_one_kw_24v_and_two_point_five_six_kwh_not_six_kw():
    d = _design(120)
    assert d.feasible
    assert d.inverter_rated_kw == 1
    assert d.battery_voltage == pytest.approx(25.6)
    assert d.battery_total_kwh == pytest.approx(2.56)
    assert d.pv_capacity_kw != d.inverter_rated_kw
    assert not d.supports_grid_export
    assert any("not a certified grid-tie" in note for note in d.notes)
    assert d.max_pv_conversion_kw == pytest.approx(50 * 22.4 / 1000)


def test_peak_and_surge_inputs_drive_automatic_inverter_and_battery_power():
    d = _design(120, peak_load_kw=3.0, surge_load_kw=7.0)
    assert d.inverter_rated_kw >= 3 * 1.25
    assert d.battery_voltage_class == "48 V"
    assert d.max_battery_discharge_kw >= 3
    assert d.pv_capacity_kw < d.inverter_rated_kw
    assert d.battery_module_count >= 2


@pytest.mark.parametrize("monthly", [120, 300, 1000, 3000, 10000])
def test_selected_capacity_power_and_voltage_meet_demand(monthly):
    d = _design(monthly)
    assert d.feasible
    assert d.pv_capacity_kw >= d.pv_required_kw
    assert d.inverter_rated_kw >= d.required_inverter_kw
    assert d.battery_total_kwh >= d.battery_required_kwh
    spec = next(s for s in INVERTER_CATALOG if s.model == d.inverter_model)
    assert spec.battery_min_v <= d.battery_voltage_min
    assert d.battery_voltage_max <= spec.battery_max_v
    assert d.max_battery_discharge_kw >= d.peak_load_kw
    assert d.max_pv_input_kw >= d.pv_capacity_kw


def test_demands_above_old_eighteen_kw_catalog_get_larger_design():
    d = _design(3000)
    assert d.feasible and d.inverter_rated_kw > 18
    assert d.battery_voltage_class == "High voltage"
    assert 4 <= d.battery_series_modules <= 12
    assert d.inverter_phase_count == 3
    assert any("three-phase electrical service" in note for note in d.notes)


def test_higher_capacity_uses_identical_parallel_inverters_not_a_clamp():
    d = _design(10000)
    assert d.feasible and d.inverter_count > 1
    assert d.inverter_rated_kw == d.inverter_unit_kw * d.inverter_count
    assert d.battery_parallel_strings <= 2 * d.inverter_count


def test_hv_series_does_not_multiply_current():
    d = _design(3000)
    battery = BATTERY_CATALOG["High voltage"]
    assert d.battery_discharge_current_a <= battery.discharge_current_a * d.battery_parallel_strings
    assert d.battery_discharge_current_a == 50 * d.battery_parallel_strings
    assert d.battery_total_kwh == pytest.approx(d.battery_module_count * battery.module_kwh)


def test_unsupported_demand_is_an_explicit_failure_not_undersized_recommendation():
    d = _design(1_000_000)
    assert not d.feasible and d.error
    assert d.inverter_rated_kw == 0


def test_custom_hourly_profile_is_authoritative_for_nighttime_storage():
    d = select_equipment_design(300, [0] * 12 + [100 / 12] * 12, 4.5, 80)
    assert d.nighttime_kwh == pytest.approx(daily_consumption_kwh(300))
    assert d.daytime_kwh == 0
    assert d.battery_total_kwh >= d.battery_required_kwh > 13


@pytest.mark.parametrize("profile, enabled", [([100/12]*12 + [0]*12, True), (default_hourly_percentages(70), False)])
def test_no_storage_for_zero_nighttime_demand_or_disabled_storage(profile, enabled):
    d = select_equipment_design(300, profile, 4.5, 80, storage_enabled=enabled)
    assert d.feasible
    assert d.battery_total_kwh == d.battery_voltage == d.battery_module_count == 0
    assert d.max_battery_charge_kw == d.max_battery_discharge_kw == 0
    assert not d.storage_enabled


@pytest.mark.parametrize("profile, enabled", [([100/12]*12 + [0]*12, True), (default_hourly_percentages(70), False)])
def test_small_no_battery_client_skips_battery_dependent_victron_assembly(profile, enabled):
    d = select_equipment_design(120, profile, 4.5, 80, storage_enabled=enabled)
    assert d.feasible and d.inverter_rated_kw == 3
    assert d.battery_total_kwh == 0
    assert "Deye" in d.inverter_model
    assert d.supports_grid_export


def test_battery_dod_is_limited_by_selected_battery_data():
    d = _design(300, battery_dod_pct=100)
    assert d.effective_dod_pct == BATTERY_CATALOG[d.battery_voltage_class].max_dod_pct
    assert any("Depth of discharge limited" in note for note in d.notes)


def test_surge_selection_and_limitations_are_reported():
    d = _design(120, peak_load_kw=0.5, surge_load_kw=2.0)
    assert d.inverter_surge_kw >= 2
    assert d.battery_pulse_current_a * d.battery_voltage_min / 1000 * d.inverter_efficiency_pct / 100 >= 2
    assert any("duration, BMS limits" in note for note in d.notes)


@pytest.mark.parametrize("shape", [[], [0] * 12, [1e308] * 12, ["wrong"] * 12])
def test_invalid_solar_profile_fails_selection_without_a_substitute(shape):
    d = _design(harvest_pct=shape)
    assert not d.feasible and "Solar profile" in d.error


def test_state_refresh_uses_current_project_optional_inputs_and_exposes_metadata():
    state = AppState()
    state.project.monthly_kwh = 300
    state.project.peak_load_kw = 4
    state.project.surge_load_kw = 8
    state.project.storage_enabled = False
    state.hourly_pct = default_hourly_percentages(70)
    d = refresh_equipment_design(state)
    assert state.design is d
    assert state.inverter_rated_power_kw == d.inverter_rated_kw
    assert state.battery_voltage == 0
    assert state.peak_load_kw == 4
    assert d.as_dict()["sources"]


def test_all_sky_calibration_preserves_weighted_production():
    factors = {"Sunny": 100, "Cloudy": 60, "Rainy": 30}
    mix = {"Sunny": 60, "Cloudy": 25, "Rainy": 15}
    sunny_psh = calibrated_peak_sun_hours(4.5, factors, mix, True)
    weighted = sum(sunny_psh * factors[n] / 100 * mix[n] / 100 for n in mix)
    assert weighted == pytest.approx(4.5)
    assert calibrated_peak_sun_hours(4.5, factors, mix, False) == 4.5
    assert calibrated_peak_sun_hours(0, factors, mix, True) == 0


def test_numeric_strings_in_saved_hourly_profile_and_weather_mix_are_normalized():
    d = select_equipment_design(300, [str(v) for v in default_hourly_percentages(70)], 4.5, 80)
    assert d.feasible
    assert calibrated_peak_sun_hours(4.5, {"Sunny": 100, "Cloudy": 60, "Rainy": 30},
                                     {"Sunny": "60", "Cloudy": "25", "Rainy": "15"}, True) > 4.5


@pytest.mark.parametrize("attr", ["peak_sun_hours", "efficiency_pct", "battery_dod_pct", "battery_efficiency_pct"])
def test_invalid_live_assumption_is_not_silently_replaced_during_refresh(attr):
    state = AppState()
    state.project.monthly_kwh = 120
    setattr(state, attr, float("nan"))
    d = refresh_equipment_design(state)
    assert not d.feasible
    assert d.error
    assert d.inverter_rated_kw == 0


@pytest.mark.parametrize("kwargs", [{"peak_load_kw": float("inf")}, {"surge_load_kw": float("nan")},
                                     {"peak_load_kw": -1}])
def test_invalid_peak_or_surge_is_not_treated_as_an_estimate(kwargs):
    d = _design(**kwargs)
    assert not d.feasible and "finite non-negative" in d.error


def test_all_sky_calibration_rejects_zero_output_and_invalid_weather_mix():
    with pytest.raises(ValueError, match="zero weather"):
        calibrated_peak_sun_hours(4.5, {n: 0 for n in ("Sunny", "Cloudy", "Rainy")},
                                 {"Sunny": 60, "Cloudy": 25, "Rainy": 15}, True)
    with pytest.raises(ValueError, match="total 100"):
        calibrated_peak_sun_hours(4.5, {"Sunny": 100, "Cloudy": 60, "Rainy": 30},
                                 {"Sunny": 100, "Cloudy": 100, "Rainy": 0}, True)
