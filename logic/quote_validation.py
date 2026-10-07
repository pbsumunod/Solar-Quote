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
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def live_float_or(value, default: float) -> float:
    """Blank live fields use their default; invalid nonblank input stays invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


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
    if not isinstance(steps, dict) or any(not isinstance(steps.get(name), dict) for name in (
        "consumption", "solar", "battery", "system_design", "simulation", "roi",
    )):
        return "The quote is missing a calculation step."
    required = {"consumption": ("hourly_pct",), "solar": ("peak_sun_hours", "efficiency_pct"),
                "battery": ("dod_pct", "efficiency_pct", "voltage"),
                "system_design": ("efficiency_pct", "max_pv_input_kw", "max_pv_charging_kw", "max_battery_charge_kw", "max_battery_discharge_kw"),
                "simulation": ("weather_factors",), "roi": ("weather_mix", "years", "export_rate", "maintenance_pct", "maintenance_fixed", "system_cost")}
    if any(key not in steps[name] for name, keys in required.items() for key in keys):
        return "The quote contains incomplete calculation inputs."
    error = validate_hourly_profile(steps["consumption"]["hourly_pct"])
    if error:
        return f"Consumption: {error}"
    for step, field, low, high, label in (
        ("solar", "peak_sun_hours", 0.01, 24, "Peak sun hours"),
        ("solar", "efficiency_pct", 0.01, 100, "System efficiency"),
        ("battery", "dod_pct", 0.01, 100, "Battery depth of discharge"),
        ("battery", "efficiency_pct", 0.01, 100, "Battery efficiency"),
        ("system_design", "efficiency_pct", 0.01, 100, "Inverter efficiency"),
    ):
        if not _finite_in_range(steps[step][field], low, high):
            return f"{step.replace('_', ' ').title()}: {label} is out of range."
    voltage_low = 0 if not steps["battery"].get("storage_enabled", True) else 0.01
    if not _finite_in_range(steps["battery"]["voltage"], voltage_low, 1500):
        return "Battery: selected voltage is out of range."
    for field in ("max_pv_input_kw", "max_pv_charging_kw", "max_battery_charge_kw", "max_battery_discharge_kw"):
        if not _finite_in_range(steps["system_design"][field], 0, 10000):
            return f"System Design: {field.replace('_', ' ').title()} must be non-negative."
    factors = steps["simulation"]["weather_factors"]
    if not isinstance(factors, dict) or set(factors) != {"Sunny", "Cloudy", "Rainy"}:
        return "Simulation: weather factors must include all three scenarios."
    for value in factors.values():
        if not _finite_in_range(value, 0, 100):
            return "Simulation: Weather factors must be between 0% and 100%."
    harvest = steps["simulation"].get("harvest_pct")
    if harvest is not None and (not isinstance(harvest, list) or len(harvest) != 12 or not all(_finite_in_range(v, 0, 100) for v in harvest) or sum(harvest) <= 0):
        return "Simulation: solar harvest must have 12 finite values and a positive total."
    for name in ("solar", "battery", "system_design"):
        if steps[name].get("selection_error"):
            return f"{name.replace('_', ' ').title()}: {steps[name]['selection_error']}"
    error = validate_weather_mix(steps["roi"]["weather_mix"])
    if error:
        return f"Savings & ROI: {error}"
    years = steps["roi"]["years"]
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        return "Savings & ROI: Simulation years must be between 1 and 50."
    for field in ("export_rate", "maintenance_pct", "maintenance_fixed", "system_cost"):
        if not _finite_in_range(steps["roi"][field], 0, 1e12):
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be non-negative."
    return validate_roi_assumptions(steps["roi"])


def validate_roi_assumptions(values: dict) -> str | None:
    for field in ("inflation_pct", "maintenance_inflation_pct", "discount_rate_pct"):
        if not _finite_in_range(values.get(field, 0), -99, 100):
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be between -99% and 100%."
    for field in ("pv_degradation_pct", "battery_degradation_pct"):
        if not _finite_in_range(values.get(field, 0), 0, 20):
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be between 0% and 20%."
    for field in ("battery_replacement_cost", "inverter_replacement_cost"):
        if not _finite_in_range(values.get(field, 0), 0, 1e12):
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be a finite non-negative cost."
    for field in ("battery_replacement_years", "inverter_replacement_years"):
        number = values.get(field, 0)
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 50:
            return f"Savings & ROI: {field.replace('_', ' ').title()} must be a whole number from 0 to 50."
    if values.get("maintenance_method", "percentage") not in ("percentage", "fixed"):
        return "Savings & ROI: choose a valid maintenance method."
    return None
