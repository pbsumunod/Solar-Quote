"""Hourly DC solar / battery / AC load model with explicit conversion losses.

PV system efficiency excludes inverter conversion. Solar production and battery
charging are DC kWh; loads, battery discharge delivered to load, imports and exports
are AC kWh. Battery round-trip loss is applied on discharge, also used in sizing.
Each interval is one hour, so power limits multiply by 1 h.
"""

from dataclasses import dataclass, field
import math

DEFAULT_SOLAR_HARVEST_PCT = [5, 12, 25, 45, 70, 95, 95, 70, 45, 25, 12, 5]
DEFAULT_WEATHER_FACTORS = {"Sunny": 100.0, "Cloudy": 60.0, "Rainy": 30.0}


def default_solar_harvest_pct() -> list[float]:
    return list(DEFAULT_SOLAR_HARVEST_PCT)


def _nonnegative(name, value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number.")


def base_daily_production_kwh(pv_capacity_kw: float, peak_sun_hours: float, system_efficiency_pct: float) -> float:
    for name, value in (("PV capacity", pv_capacity_kw), ("Peak sun hours", peak_sun_hours),
                        ("System efficiency", system_efficiency_pct)):
        _nonnegative(name, value)
    if peak_sun_hours > 24 or system_efficiency_pct > 100:
        raise ValueError("Solar assumptions are outside their valid ranges.")
    value = pv_capacity_kw * peak_sun_hours * system_efficiency_pct / 100
    if not math.isfinite(value):
        raise ValueError("Solar production exceeds the supported numerical range.")
    return value


def hourly_solar_kwh(pv_capacity_kw: float, peak_sun_hours: float, system_efficiency_pct: float,
                     weather_factor_pct: float, harvest_pct: list[float]) -> list[float]:
    """Redistribute derated DC production over the 12 daytime hours."""
    _nonnegative("Weather factor", weather_factor_pct)
    if weather_factor_pct > 100:
        raise ValueError("Weather factor must be between 0 and 100%.")
    if len(harvest_pct) != 12:
        raise ValueError("Solar harvest profile must contain 12 daytime values.")
    for value in harvest_pct:
        _nonnegative("Harvest profile", value)
    daily = base_daily_production_kwh(pv_capacity_kw, peak_sun_hours, system_efficiency_pct) * weather_factor_pct / 100
    total = sum(harvest_pct)
    if not math.isfinite(total):
        raise ValueError("Solar harvest profile exceeds the supported numerical range.")
    day = [daily * value / total for value in harvest_pct] if total > 0 else [0.0] * 12
    return day + [0.0] * 12


@dataclass
class HourResult:
    hour_label: str
    consumption_kwh: float
    solar_kwh: float
    solar_to_load_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    grid_purchase_kwh: float
    grid_export_kwh: float
    curtailed_kwh: float
    soc_start_kwh: float
    soc_end_kwh: float
    soc_end_pct: float
    conversion_loss_kwh: float = 0.0
    battery_loss_kwh: float = 0.0
    clipped_kwh: float = 0.0


@dataclass
class SimulationResult:
    hours: list = field(default_factory=list)
    total_consumption_kwh: float = 0.0
    total_solar_kwh: float = 0.0
    total_solar_to_load_kwh: float = 0.0
    total_battery_charge_kwh: float = 0.0
    total_battery_discharge_kwh: float = 0.0
    total_grid_purchase_kwh: float = 0.0
    total_grid_export_kwh: float = 0.0
    total_curtailed_kwh: float = 0.0
    total_conversion_loss_kwh: float = 0.0
    total_battery_loss_kwh: float = 0.0
    total_clipped_kwh: float = 0.0
    converged: bool = True
    iterations: int = 1
    soc_residual_kwh: float = 0.0


def run_hourly_simulation(
    hourly_consumption_kwh: list[float], hourly_solar_kwh_values: list[float],
    hour_labels: list[str], battery_total_kwh: float, battery_dod_pct: float,
    battery_efficiency_pct: float, max_battery_charge_kw: float,
    max_battery_discharge_kw: float, grid_export_enabled: bool, initial_soc_kwh: float,
    *, inverter_rated_power_kw: float | None = None, inverter_efficiency_pct: float = 100,
    max_pv_input_kw: float | None = None, max_pv_charging_kw: float | None = None,
) -> SimulationResult:
    """Prioritize load, then DC battery charge, then constrained AC export.

    Optional hardware limits preserve callers of the original pure-logic API.
    max_battery_discharge_kw is power delivered on the AC side. Imports may supply
    load beyond the inverter rating; solar plus battery AC output cannot exceed it.
    """
    if not (len(hour_labels) == len(hourly_consumption_kwh) == len(hourly_solar_kwh_values)) or not hour_labels:
        raise ValueError("Load, solar and hour labels must have the same nonzero length.")
    for name, values in (("Load", hourly_consumption_kwh), ("Solar", hourly_solar_kwh_values)):
        for value in values:
            _nonnegative(name, value)
        if not math.isfinite(sum(values)):
            raise ValueError(f"{name} total exceeds the supported numerical range.")
    for name, value in (("Battery capacity", battery_total_kwh), ("Battery charge limit", max_battery_charge_kw),
                        ("Battery discharge limit", max_battery_discharge_kw), ("Initial SOC", initial_soc_kwh)):
        _nonnegative(name, value)
    if not (math.isfinite(battery_dod_pct) and 0 <= battery_dod_pct <= 100 and
            math.isfinite(battery_efficiency_pct) and 0 < battery_efficiency_pct <= 100 and
            math.isfinite(inverter_efficiency_pct) and 0 < inverter_efficiency_pct <= 100):
        raise ValueError("Battery and inverter efficiencies / DOD are outside their valid ranges.")
    for name, value in (("Inverter rating", inverter_rated_power_kw), ("PV input limit", max_pv_input_kw),
                        ("PV charge limit", max_pv_charging_kw)):
        if value is not None:
            _nonnegative(name, value)
    inv_eff, batt_eff = inverter_efficiency_pct / 100, battery_efficiency_pct / 100
    inverter_limit = inverter_rated_power_kw if inverter_rated_power_kw is not None else math.inf
    pv_limit = max_pv_input_kw if max_pv_input_kw is not None else math.inf
    pv_charge_limit = max_pv_charging_kw if max_pv_charging_kw is not None else math.inf
    min_soc = battery_total_kwh * (1 - battery_dod_pct / 100)
    soc = max(min_soc, min(battery_total_kwh, initial_soc_kwh))
    result = SimulationResult()

    for label, consumption, solar in zip(hour_labels, hourly_consumption_kwh, hourly_solar_kwh_values):
        start = soc
        dc_available = min(solar, pv_limit)
        clipped = solar - dc_available
        curtailed = clipped
        solar_to_load = min(consumption, dc_available * inv_eff, inverter_limit)
        dc_to_load = solar_to_load / inv_eff
        remaining_dc = max(0.0, dc_available - dc_to_load)
        remaining_load = max(0.0, consumption - solar_to_load)
        ac_headroom = max(0.0, inverter_limit - solar_to_load)
        charge = min(remaining_dc, max_battery_charge_kw, pv_charge_limit, max(0.0, battery_total_kwh - soc))
        soc += charge
        remaining_dc -= charge
        export = min(remaining_dc * inv_eff, ac_headroom) if grid_export_enabled else 0.0
        dc_export = export / inv_eff
        unused_dc = max(0.0, remaining_dc - dc_export)
        curtailed += unused_dc
        if grid_export_enabled:
            clipped += unused_dc
        conversion_loss = dc_to_load + dc_export - solar_to_load - export
        available_ac = max(0.0, soc - min_soc) * batt_eff * inv_eff
        discharge = min(remaining_load, max_battery_discharge_kw, available_ac, max(0.0, ac_headroom - export))
        dc_discharge = discharge / inv_eff
        soc_draw = dc_discharge / batt_eff
        soc -= soc_draw
        battery_loss = soc_draw - dc_discharge
        conversion_loss += dc_discharge - discharge
        grid = max(0.0, remaining_load - discharge)
        soc = max(min_soc, min(battery_total_kwh, soc))
        hour = HourResult(
            label, consumption, solar, solar_to_load, charge, discharge, grid, export,
            curtailed, start, soc, soc / battery_total_kwh * 100 if battery_total_kwh else 0,
            conversion_loss, battery_loss, clipped,
        )
        result.hours.append(hour)
        for name, value in (("consumption", consumption), ("solar", solar), ("solar_to_load", solar_to_load),
                            ("battery_charge", charge), ("battery_discharge", discharge), ("grid_purchase", grid),
                            ("grid_export", export), ("curtailed", curtailed), ("conversion_loss", conversion_loss),
                            ("battery_loss", battery_loss), ("clipped", clipped)):
            attr = f"total_{name}_kwh"
            setattr(result, attr, getattr(result, attr) + value)
    result.soc_residual_kwh = result.hours[-1].soc_end_kwh - result.hours[0].soc_start_kwh
    return result


def run_steady_state_simulation(
    hourly_consumption_kwh: list[float], hourly_solar_kwh_values: list[float],
    hour_labels: list[str], battery_total_kwh: float, battery_dod_pct: float,
    battery_efficiency_pct: float, max_battery_charge_kw: float,
    max_battery_discharge_kw: float, grid_export_enabled: bool,
    max_iterations: int = 80, tolerance_kwh: float = 1e-7, **hardware_limits,
) -> SimulationResult:
    """Find a fixed SOC cycle by bracketing; never return a draining transient.

    For this dispatch policy F(SOC)-SOC is continuous and non-increasing. Endpoint
    evaluation handles empty/full fixed cycles; bisection handles arbitrarily slow
    drift which repeated-day iteration could mistake for sustainable stored energy.
    """
    if max_iterations < 1 or not math.isfinite(tolerance_kwh) or tolerance_kwh <= 0:
        raise ValueError("Steady-state solver needs positive iteration and tolerance limits.")
    low = battery_total_kwh * (1 - battery_dod_pct / 100)
    high = battery_total_kwh

    def run(soc):
        return run_hourly_simulation(
            hourly_consumption_kwh, hourly_solar_kwh_values, hour_labels, battery_total_kwh,
            battery_dod_pct, battery_efficiency_pct, max_battery_charge_kw,
            max_battery_discharge_kw, grid_export_enabled, soc, **hardware_limits,
        )

    for iteration, guess in ((1, low), (2, high)):
        result = run(guess)
        if abs(result.soc_residual_kwh) <= tolerance_kwh:
            result.iterations = iteration
            return result
    for iteration in range(1, max_iterations + 1):
        guess = (low + high) / 2
        result = run(guess)
        result.iterations = iteration + 2
        if abs(result.soc_residual_kwh) <= tolerance_kwh:
            return result
        if result.soc_residual_kwh > 0:
            low = guess
        else:
            high = guess
    raise RuntimeError("Battery SOC did not converge; annual savings cannot use this transient cycle.")
