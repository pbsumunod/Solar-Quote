"""Savings, ROI, payback, and 25-year financial projection (Instruction.md Sections 20-26).

Annual production/consumption figures are derived by blending the three per-scenario
daily simulation results (Sunny/Cloudy/Rainy, from simulation.py) using an editable
"days per year" weather mix, then annualizing (x365). This grounds the financial
projection in the actual hourly simulation rather than a disconnected estimate, and
keeps the mix itself an editable, transparent assumption like everything else in the app.
"""

from dataclasses import dataclass
import math


def _growth_factor(percent: float, periods: int) -> float:
    if not math.isfinite(percent) or not -99 <= percent <= 100 or not 0 <= periods <= 50:
        raise ValueError("Growth rates must be between -99% and 100%, with at most 50 years.")
    return (1 + percent / 100) ** periods


def blended_annual_kwh(scenario_results: dict, weather_mix_pct: dict, attr: str) -> float:
    """Weight each scenario's daily total by its share of the year and annualize (x365)."""
    total = 0.0
    for name, pct in weather_mix_pct.items():
        result = scenario_results.get(name)
        if result is None:
            continue
        daily_value = getattr(result, attr)
        total += daily_value * (pct / 100) * 365
    return total


def annual_electricity_cost_without_solar(monthly_kwh: float, rate: float) -> float:
    """Section 20: Monthly Consumption x Electricity Rate, annualized."""
    return monthly_kwh * 12 * rate


def annual_grid_cost_with_solar(
    annual_grid_purchase_kwh: float,
    rate: float,
    annual_grid_export_kwh: float,
    export_rate: float,
    export_enabled: bool,
) -> float:
    """Section 20: only energy that actually offsets grid consumption counts as savings;
    export is compensated separately (if enabled) at its own rate.
    """
    cost = annual_grid_purchase_kwh * rate
    if export_enabled:
        cost -= annual_grid_export_kwh * export_rate
    return cost


def future_rate(base_rate: float, inflation_pct: float, year: int) -> float:
    """Section 21: Year 1 = base rate; each following year = previous x (1 + inflation)."""
    return base_rate * _growth_factor(inflation_pct, year - 1)


def maintenance_cost_for_year(
    system_cost: float,
    method: str,
    maintenance_pct: float,
    maintenance_fixed: float,
    maintenance_inflation_pct: float,
    year: int,
) -> float:
    """Section 22: percentage-of-system-cost or fixed annual amount, with optional inflation."""
    base = system_cost * (maintenance_pct / 100) if method == "percentage" else maintenance_fixed
    return base * _growth_factor(maintenance_inflation_pct, year - 1)


@dataclass
class YearRow:
    year: int
    electricity_rate: float
    grid_cost_without_solar: float
    grid_cost_with_solar: float
    electricity_savings: float
    maintenance: float
    net_savings: float
    cumulative_cash_flow: float
    replacement: float = 0.0
    discounted_net_savings: float = 0.0
    cumulative_discounted_cash_flow: float = 0.0
    energy_retention: float = 1.0


def build_projection_table(
    system_cost: float,
    base_rate: float,
    inflation_pct: float,
    annual_kwh_without_solar: float,
    annual_grid_purchase_kwh: float,
    annual_grid_export_kwh: float,
    export_rate: float,
    export_enabled: bool,
    maintenance_method: str,
    maintenance_pct: float,
    maintenance_fixed: float,
    maintenance_inflation_pct: float,
    years: int,
    *,
    pv_degradation_pct: float = 0.0,
    battery_degradation_pct: float = 0.0,
    annual_battery_discharge_kwh: float = 0.0,
    battery_replacement_years: int = 0,
    battery_replacement_cost: float = 0.0,
    inverter_replacement_years: int = 0,
    inverter_replacement_cost: float = 0.0,
    discount_rate_pct: float = 0.0,
) -> list[YearRow]:
    """Section 26: year-by-year financial projection with cumulative cash flow."""
    numbers = (system_cost, base_rate, annual_kwh_without_solar, annual_grid_purchase_kwh,
               annual_grid_export_kwh, export_rate, maintenance_pct, maintenance_fixed,
               battery_replacement_cost, inverter_replacement_cost, annual_battery_discharge_kwh)
    if any(not math.isfinite(v) or v < 0 or v > 1e15 for v in numbers):
        raise ValueError("Projection costs and energy must be finite non-negative values.")
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        raise ValueError("Projection years must be between 1 and 50.")
    if maintenance_method not in ("percentage", "fixed"):
        raise ValueError("Select a valid maintenance method.")
    for degradation in (pv_degradation_pct, battery_degradation_pct):
        if not math.isfinite(degradation) or not 0 <= degradation <= 20:
            raise ValueError("Annual degradation must be between 0% and 20%.")
    for interval in (battery_replacement_years, inverter_replacement_years):
        if isinstance(interval, bool) or not isinstance(interval, int) or not 0 <= interval <= 50:
            raise ValueError("Replacement intervals must be whole years between 0 and 50.")
    _growth_factor(inflation_pct, 0)
    _growth_factor(maintenance_inflation_pct, 0)
    _growth_factor(discount_rate_pct, 0)
    rows = []
    cumulative = -system_cost
    discounted_cumulative = -system_cost
    displaced = max(0.0, annual_kwh_without_solar - annual_grid_purchase_kwh)
    stored_displacement = min(displaced, annual_battery_discharge_kwh)
    for year in range(1, years + 1):
        pv_retention = (1 - pv_degradation_pct / 100) ** (year - 1)
        battery_age = (year - 1) % battery_replacement_years if battery_replacement_years else year - 1
        battery_retention = (1 - battery_degradation_pct / 100) ** battery_age
        retained_displacement = max(0.0, pv_retention * (displaced - stored_displacement * (1 - battery_retention)))
        purchase = annual_kwh_without_solar - retained_displacement if displaced > 0 else annual_grid_purchase_kwh
        rate = future_rate(base_rate, inflation_pct, year)
        grid_cost_without = annual_kwh_without_solar * rate
        grid_cost_with = purchase * rate
        if export_enabled:
            grid_cost_with -= annual_grid_export_kwh * pv_retention * export_rate
        electricity_savings = grid_cost_without - grid_cost_with
        maintenance = maintenance_cost_for_year(
            system_cost, maintenance_method, maintenance_pct, maintenance_fixed,
            maintenance_inflation_pct, year,
        )
        replacement = 0.0
        if year > 1 and battery_replacement_years and (year - 1) % battery_replacement_years == 0:
            replacement += battery_replacement_cost
        if year > 1 and inverter_replacement_years and (year - 1) % inverter_replacement_years == 0:
            replacement += inverter_replacement_cost
        net_savings = electricity_savings - maintenance - replacement
        cumulative += net_savings
        discounted = net_savings / _growth_factor(discount_rate_pct, year)
        discounted_cumulative += discounted
        if not all(math.isfinite(v) for v in (net_savings, cumulative, discounted, discounted_cumulative)):
            raise ValueError("Projection exceeded the supported numeric range.")
        rows.append(YearRow(
            year=year, electricity_rate=rate, grid_cost_without_solar=grid_cost_without,
            grid_cost_with_solar=grid_cost_with, electricity_savings=electricity_savings,
            maintenance=maintenance, net_savings=net_savings, cumulative_cash_flow=cumulative,
            replacement=replacement, discounted_net_savings=discounted,
            cumulative_discounted_cash_flow=discounted_cumulative, energy_retention=pv_retention,
        ))
    return rows


def calculate_payback_years(rows: list[YearRow], system_cost: float) -> float | None:
    """Section 24: fractional payback year via linear interpolation within the payback year."""
    if system_cost <= 0:
        return None
    prev_cumulative = -system_cost
    for row in rows:
        if row.cumulative_cash_flow >= 0:
            if row.net_savings <= 0:
                return None
            fraction = (-prev_cumulative) / row.net_savings
            return (row.year - 1) + fraction
        prev_cumulative = row.cumulative_cash_flow
    return None


def calculate_discounted_payback_years(rows: list[YearRow], system_cost: float) -> float | None:
    if system_cost <= 0:
        return None
    previous = -system_cost
    for row in rows:
        if row.cumulative_discounted_cash_flow >= 0 and row.discounted_net_savings > 0:
            return row.year - 1 + (-previous / row.discounted_net_savings)
        previous = row.cumulative_discounted_cash_flow
    return None


def net_present_value(rows: list[YearRow], system_cost: float) -> float:
    return rows[-1].cumulative_discounted_cash_flow if rows else -system_cost


def total_electricity_savings(rows: list[YearRow]) -> float:
    return sum(row.electricity_savings for row in rows)


def net_benefit(rows: list[YearRow], system_cost: float) -> float:
    return rows[-1].cumulative_cash_flow if rows else -system_cost


def roi_percent(net_benefit_value: float, system_cost: float) -> float:
    """Section 24: Total Net Benefit / Initial Investment x 100."""
    return (net_benefit_value / system_cost * 100) if system_cost > 0 else 0.0


def projection_sensitivity(**projection_inputs) -> list[dict]:
    """One variable at a time, retaining the chosen equipment and lifetime inputs.

    Yield cases scale first-year energy displacement/export, capped by load;
    they approximate resource uncertainty rather than rerunning hourly dispatch.
    """
    scenarios = (
        ("Base assumptions", None, 1.0),
        ("Installed cost -10%", "system_cost", 0.9),
        ("Installed cost +10%", "system_cost", 1.1),
        ("Retail tariff -10%", "base_rate", 0.9),
        ("Retail tariff +10%", "base_rate", 1.1),
        ("Solar yield -20%", "yield", 0.8),
        ("Solar yield +20%", "yield", 1.2),
    )
    results = []
    for label, field, multiplier in scenarios:
        inputs = dict(projection_inputs)
        if field == "yield":
            baseline = inputs["annual_kwh_without_solar"]
            displacement = max(0, baseline - inputs["annual_grid_purchase_kwh"])
            inputs["annual_grid_purchase_kwh"] = max(0, baseline - displacement * multiplier)
            inputs["annual_grid_export_kwh"] *= multiplier
            inputs["annual_battery_discharge_kwh"] = min(baseline, inputs.get("annual_battery_discharge_kwh", 0) * multiplier)
        elif field:
            inputs[field] *= multiplier
        rows = build_projection_table(**inputs)
        cost = inputs["system_cost"]
        results.append({"scenario": label, "system_cost": cost, "base_rate": inputs["base_rate"],
                        "annual_grid_purchase_kwh": inputs["annual_grid_purchase_kwh"],
                        "annual_grid_export_kwh": inputs["annual_grid_export_kwh"],
                        "npv": net_present_value(rows, cost),
                        "payback_years": calculate_payback_years(rows, cost),
                        "roi_pct": roi_percent(net_benefit(rows, cost), cost) if cost > 0 else None})
    return results
