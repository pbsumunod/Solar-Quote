"""Weather scenario and hourly energy-flow simulation (Instruction.md Sections 14-19).

Battery efficiency convention: the round-trip loss is applied entirely on discharge,
matching Section 10's sizing formula (Nighttime Energy / DOD / Efficiency) -- to deliver
X kWh to the load, X / efficiency kWh must be drawn from the battery's state of charge.
Charging is treated as lossless into the state-of-charge figure. This is a deliberate
simplification (the spec does not define a hourly-level convention), kept consistent
with the one formula the spec does give.
"""

from dataclasses import dataclass, field

DEFAULT_SOLAR_HARVEST_PCT = [5, 12, 25, 45, 70, 95, 95, 70, 45, 25, 12, 5]  # 6 AM - 5 PM
DEFAULT_WEATHER_FACTORS = {"Sunny": 100.0, "Cloudy": 60.0, "Rainy": 30.0}


def default_solar_harvest_pct() -> list[float]:
    return list(DEFAULT_SOLAR_HARVEST_PCT)


def base_daily_production_kwh(pv_capacity_kw: float, peak_sun_hours: float, system_efficiency_pct: float) -> float:
    """Inverse of Section 8's sizing formula: PV Capacity x Peak Sun Hours x System Efficiency."""
    return pv_capacity_kw * peak_sun_hours * (system_efficiency_pct / 100)


def hourly_solar_kwh(
    pv_capacity_kw: float,
    peak_sun_hours: float,
    system_efficiency_pct: float,
    weather_factor_pct: float,
    harvest_pct: list[float],
) -> list[float]:
    """Section 15: normalize the harvest-profile SHAPE against the true total daily
    production (not a naive capacity x percentage multiplication), then apply the weather
    scenario factor. Returns 24 hourly values aligned with calculations.HOUR_LABELS
    (the last 12 -- nighttime -- are always 0).

    The shape is deliberately concentrated around solar noon (matching how real solar
    irradiance is peaked, not flat) so that the peak hour's SHARE of the daily total is
    close to the shape's own peak percentage -- e.g. with the default shape, the peak hour
    receives ~19% of the day's energy, so a system with peak_sun_hours close to the app's
    4.5h default sees peak-hour output land near capacity x system_efficiency x 95%, not
    diluted well below what "95%" suggests. peak_sun_hours + system_efficiency still fully
    control the total daily/annual kWh (and thus ROI) -- the shape only ever redistributes
    that same fixed total across hours, so tuning it here never changes Solar Sizing's
    numbers or the financial results.
    """
    base = base_daily_production_kwh(pv_capacity_kw, peak_sun_hours, system_efficiency_pct)
    total_daily_kwh = base * (weather_factor_pct / 100)

    shape_total = sum(harvest_pct)
    if shape_total <= 0:
        day_hours = [0.0] * 12
    else:
        day_hours = [total_daily_kwh * (p / shape_total) for p in harvest_pct]
    return day_hours + [0.0] * 12


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


def run_hourly_simulation(
    hourly_consumption_kwh: list[float],
    hourly_solar_kwh_values: list[float],
    hour_labels: list[str],
    battery_total_kwh: float,
    battery_dod_pct: float,
    battery_efficiency_pct: float,
    max_battery_charge_kw: float,
    max_battery_discharge_kw: float,
    grid_export_enabled: bool,
    initial_soc_kwh: float,
) -> SimulationResult:
    """Section 16-17: hourly energy-flow simulation with battery SOC tracking.

    Priority when solar is available: load first, then battery charge, then export/curtail.
    Priority when solar is insufficient (including all nighttime hours): battery discharge
    covers the shortfall, then grid covers whatever the battery cannot. `initial_soc_kwh` is
    the battery's state of charge at the start of the simulated cycle (6 AM); pass the
    result of run_steady_state_simulation() to find the value that makes the 24-hour cycle
    self-consistent rather than guessing one.
    """
    min_soc = battery_total_kwh * (1 - battery_dod_pct / 100)
    max_soc = battery_total_kwh
    efficiency = battery_efficiency_pct / 100
    soc = max(min_soc, min(max_soc, initial_soc_kwh))

    result = SimulationResult()

    for label, consumption, solar in zip(hour_labels, hourly_consumption_kwh, hourly_solar_kwh_values):
        soc_start = soc
        solar_to_load = min(consumption, solar)
        remaining_load = consumption - solar_to_load
        remaining_solar = solar - solar_to_load

        battery_charge = 0.0
        battery_discharge = 0.0
        grid_export = 0.0
        curtailed = 0.0
        grid_purchase = 0.0

        if remaining_solar > 0:
            headroom = max(0.0, max_soc - soc)
            battery_charge = min(remaining_solar, max_battery_charge_kw, headroom)
            soc += battery_charge
            remaining_solar -= battery_charge
            if remaining_solar > 0:
                if grid_export_enabled:
                    grid_export = remaining_solar
                else:
                    curtailed = remaining_solar
        elif remaining_load > 0:
            available = max(0.0, (soc - min_soc) * efficiency) if efficiency > 0 else 0.0
            battery_discharge = min(remaining_load, max_battery_discharge_kw, available)
            soc -= (battery_discharge / efficiency) if efficiency > 0 else 0.0
            remaining_load -= battery_discharge
            if remaining_load > 0:
                grid_purchase = remaining_load

        soc = max(min_soc, min(max_soc, soc))
        soc_pct = (soc / max_soc * 100) if max_soc > 0 else 0.0

        result.hours.append(HourResult(
            hour_label=label, consumption_kwh=consumption, solar_kwh=solar,
            solar_to_load_kwh=solar_to_load, battery_charge_kwh=battery_charge,
            battery_discharge_kwh=battery_discharge, grid_purchase_kwh=grid_purchase,
            grid_export_kwh=grid_export, curtailed_kwh=curtailed,
            soc_start_kwh=soc_start, soc_end_kwh=soc, soc_end_pct=soc_pct,
        ))

        result.total_consumption_kwh += consumption
        result.total_solar_kwh += solar
        result.total_solar_to_load_kwh += solar_to_load
        result.total_battery_charge_kwh += battery_charge
        result.total_battery_discharge_kwh += battery_discharge
        result.total_grid_purchase_kwh += grid_purchase
        result.total_grid_export_kwh += grid_export
        result.total_curtailed_kwh += curtailed

    return result


def run_steady_state_simulation(
    hourly_consumption_kwh: list[float],
    hourly_solar_kwh_values: list[float],
    hour_labels: list[str],
    battery_total_kwh: float,
    battery_dod_pct: float,
    battery_efficiency_pct: float,
    max_battery_charge_kw: float,
    max_battery_discharge_kw: float,
    grid_export_enabled: bool,
    max_iterations: int = 50,
    tolerance_kwh: float = 0.001,
) -> SimulationResult:
    """Solve for the battery's starting state of charge that makes the 24-hour cycle
    self-consistent -- i.e. the SOC at the end of the simulated day equals the SOC it
    started with -- by repeatedly re-running the simulation, feeding each run's ending
    SOC back in as the next run's starting SOC, until it converges. This models a
    battery cycling the same way day after day rather than an arbitrary starting guess.
    """
    min_soc = battery_total_kwh * (1 - battery_dod_pct / 100)
    max_soc = battery_total_kwh
    guess = max(min_soc, min(max_soc, battery_total_kwh * 0.5))

    result = None
    for _ in range(max_iterations):
        result = run_hourly_simulation(
            hourly_consumption_kwh=hourly_consumption_kwh,
            hourly_solar_kwh_values=hourly_solar_kwh_values,
            hour_labels=hour_labels,
            battery_total_kwh=battery_total_kwh,
            battery_dod_pct=battery_dod_pct,
            battery_efficiency_pct=battery_efficiency_pct,
            max_battery_charge_kw=max_battery_charge_kw,
            max_battery_discharge_kw=max_battery_discharge_kw,
            grid_export_enabled=grid_export_enabled,
            initial_soc_kwh=guess,
        )
        end_soc = result.hours[-1].soc_end_kwh
        if abs(end_soc - guess) < tolerance_kwh:
            break
        guess = end_soc

    return result
