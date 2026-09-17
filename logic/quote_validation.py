"""Checks shared by navigation, saving, and report export."""

import math


def _finite_in_range(value, low: float, high: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and low <= number <= high


def finite_float_or(value, default: float) -> float:
    """Keep malformed saved numbers out of live calculations."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def validate_hourly_profile(values) -> str | None:
    if not isinstance(values, list) or len(values) != 24:
        return "Hourly load profile must contain 24 values."
    if not all(_finite_in_range(value, 0, 100) for value in values):
        return "Hourly percentages must be between 0 and 100."
    if abs(sum(float(value) for value in values) - 100) > 0.05:
        return "Hourly percentages must total 100%."
    return None


def validate_weather_mix(values) -> str | None:
    if not isinstance(values, dict) or set(values) != {"Sunny", "Cloudy", "Rainy"}:
        return "Weather mix must include Sunny, Cloudy, and Rainy."
    if not all(_finite_in_range(value, 0, 100) for value in values.values()):
        return "Weather mix percentages must be between 0 and 100."
    if abs(sum(float(value) for value in values.values()) - 100) > 0.05:
        return "Weather mix percentages must total 100%."
    return None


def validate_quote_steps(steps: dict) -> str | None:
    error = validate_hourly_profile(steps["consumption"]["hourly_pct"])
    if error:
        return f"Consumption: {error}"
    for step, field, low, high, label in (
        ("solar", "peak_sun_hours", 0.01, 24, "Peak sun hours"),
        ("solar", "efficiency_pct", 0.01, 100, "System efficiency"),
        ("battery", "dod_pct", 0.01, 100, "Battery depth of discharge"),
        ("battery", "efficiency_pct", 0.01, 100, "Battery efficiency"),
        ("battery", "voltage", 0.01, float("inf"), "Battery voltage"),
        ("system_design", "efficiency_pct", 0.01, 100, "Inverter efficiency"),
    ):
        if not _finite_in_range(steps[step][field], low, high):
            return f"{step.replace('_', ' ').title()}: {label} is out of range."
    for field in ("max_pv_input_kw", "max_pv_charging_kw", "max_battery_charge_kw", "max_battery_discharge_kw"):
        if not _finite_in_range(steps["system_design"][field], 0, float("inf")):
            return f"System Design: {field.replace('_', ' ').title()} must be non-negative."
    for value in steps["simulation"]["weather_factors"].values():
        if not _finite_in_range(value, 0, float("inf")):
            return "Simulation: Weather factors must be non-negative numbers."
    error = validate_weather_mix(steps["roi"]["weather_mix"])
    if error:
        return f"Savings & ROI: {error}"
    years = steps["roi"]["years"]
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        return "Savings & ROI: Simulation years must be between 1 and 50."
    for field in ("export_rate", "maintenance_pct", "maintenance_fixed", "system_cost"):
        if not _finite_in_range(steps["roi"][field], 0, float("inf")):
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be non-negative."
    return None
