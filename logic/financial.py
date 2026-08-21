"""Savings, ROI, payback, and 25-year financial projection (Instruction.md Sections 20-26).

Annual production/consumption figures are derived by blending the three per-scenario
daily simulation results (Sunny/Cloudy/Rainy, from simulation.py) using an editable
"days per year" weather mix, then annualizing (x365). This grounds the financial
projection in the actual hourly simulation rather than a disconnected estimate, and
keeps the mix itself an editable, transparent assumption like everything else in the app.
"""

from dataclasses import dataclass


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
    return base_rate * ((1 + inflation_pct / 100) ** (year - 1))


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
    return base * ((1 + maintenance_inflation_pct / 100) ** (year - 1))


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
) -> list[YearRow]:
    """Section 26: year-by-year financial projection with cumulative cash flow."""
    rows = []
    cumulative = -system_cost
    for year in range(1, years + 1):
        rate = future_rate(base_rate, inflation_pct, year)
        grid_cost_without = annual_kwh_without_solar * rate
        grid_cost_with = annual_grid_purchase_kwh * rate
        if export_enabled:
            grid_cost_with -= annual_grid_export_kwh * export_rate
        electricity_savings = grid_cost_without - grid_cost_with
        maintenance = maintenance_cost_for_year(
            system_cost, maintenance_method, maintenance_pct, maintenance_fixed,
            maintenance_inflation_pct, year,
        )
        net_savings = electricity_savings - maintenance
        cumulative += net_savings
        rows.append(YearRow(
            year=year, electricity_rate=rate, grid_cost_without_solar=grid_cost_without,
            grid_cost_with_solar=grid_cost_with, electricity_savings=electricity_savings,
            maintenance=maintenance, net_savings=net_savings, cumulative_cash_flow=cumulative,
        ))
    return rows


def calculate_payback_years(rows: list[YearRow], system_cost: float) -> float | None:
    """Section 24: fractional payback year via linear interpolation within the payback year."""
    prev_cumulative = -system_cost
    for row in rows:
        if row.cumulative_cash_flow >= 0:
            if row.net_savings <= 0:
                return None
            fraction = (-prev_cumulative) / row.net_savings
            return (row.year - 1) + fraction
        prev_cumulative = row.cumulative_cash_flow
    return None


def total_electricity_savings(rows: list[YearRow]) -> float:
    return sum(row.electricity_savings for row in rows)


def net_benefit(rows: list[YearRow], system_cost: float) -> float:
    return rows[-1].cumulative_cash_flow if rows else -system_cost


def roi_percent(net_benefit_value: float, system_cost: float) -> float:
    """Section 24: Total Net Benefit / Initial Investment x 100."""
    return (net_benefit_value / system_cost * 100) if system_cost > 0 else 0.0
