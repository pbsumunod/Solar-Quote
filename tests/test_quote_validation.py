from logic.calculations import default_hourly_percentages
from logic.models import Project
from logic.quote_validation import finite_float_or, validate_hourly_profile, validate_quote_steps, validate_weather_mix
from screens.client_screen import ClientScreen


def test_hourly_profile_rejects_missing_bad_and_nonfinite_values():
    profile = default_hourly_percentages(70)
    assert validate_hourly_profile(profile) is None
    assert validate_hourly_profile(profile[:-1]) is not None
    assert validate_hourly_profile([0.0] * 24) is not None
    assert validate_hourly_profile([float("nan")] + profile[1:]) is not None
    assert validate_hourly_profile([-1.0] + profile[1:]) is not None


def test_weather_mix_and_projection_years_are_validated():
    mix = {"Sunny": 60, "Cloudy": 25, "Rainy": 15}
    steps = {"consumption": {"hourly_pct": default_hourly_percentages(70)},
             "solar": {"peak_sun_hours": 4.5, "efficiency_pct": 80},
             "battery": {"dod_pct": 80, "efficiency_pct": 90, "voltage": 48},
             "system_design": {"efficiency_pct": 97, "max_pv_input_kw": 8,
                               "max_pv_charging_kw": 6, "max_battery_charge_kw": 5,
                               "max_battery_discharge_kw": 5},
             "simulation": {"weather_factors": {"Sunny": 100, "Cloudy": 60, "Rainy": 30}},
             "roi": {"weather_mix": mix, "years": 25, "export_rate": 6,
                     "maintenance_pct": 1, "maintenance_fixed": 10000, "system_cost": 200000}}
    assert validate_quote_steps(steps) is None
    assert validate_weather_mix({"Sunny": 100, "Cloudy": 100, "Rainy": 0}) is not None
    steps["roi"]["years"] = 1000000
    assert "years" in validate_quote_steps(steps).lower()
    steps["roi"]["years"] = 25
    steps["battery"]["dod_pct"] = 150
    assert "Battery" in validate_quote_steps(steps)


def test_nonfinite_saved_values_fall_back_before_calculation():
    assert finite_float_or("nan", 4.5) == 4.5
    assert finite_float_or("inf", 4.5) == 4.5
    assert finite_float_or("2.5", 4.5) == 2.5


def test_client_rejects_bad_dates_and_nonfinite_numbers():
    project = Project(client_name="Tester", monthly_kwh=300, project_date="2026-02-30")
    assert "Date" in ClientScreen._validate(None, project)
    project.project_date = "20260917"
    assert "Date" in ClientScreen._validate(None, project)
    project.project_date = "2026-09-17"
    project.monthly_kwh = float("inf")
    assert "Consumption" in ClientScreen._validate(None, project)
