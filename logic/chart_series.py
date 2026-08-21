"""Shared hourly-chart series construction for a SimulationResult, used by both the
Simulation screen (live chart) and the Report screen (PowerPoint chart-slide export)
so the two always draw the exact same lines from the exact same data.
"""

from logic.calculations import HOUR_LABELS
from logic.simulation import HourResult

SERIES_COLORS = {
    "Consumption": (0.80, 0.15, 0.15, 1),
    "Solar/Harvest": (0.95, 0.75, 0.05, 1),
    "Grid": (0.15, 0.42, 0.80, 1),
    "Battery": (0.15, 0.55, 0.25, 1),
}


def series_for_result(result, battery_total_kwh: float) -> tuple[list[tuple], list[str], list]:
    hours = list(result.hours)
    first = hours[0]
    wrap_soc_kwh = first.soc_start_kwh
    wrap_soc_pct = (wrap_soc_kwh / battery_total_kwh * 100) if battery_total_kwh else 0.0
    wrap_hour = HourResult(
        hour_label="6 AM", consumption_kwh=first.consumption_kwh, solar_kwh=first.solar_kwh,
        solar_to_load_kwh=first.solar_to_load_kwh, battery_charge_kwh=first.battery_charge_kwh,
        battery_discharge_kwh=first.battery_discharge_kwh, grid_purchase_kwh=first.grid_purchase_kwh,
        grid_export_kwh=first.grid_export_kwh, curtailed_kwh=first.curtailed_kwh,
        soc_start_kwh=wrap_soc_kwh, soc_end_kwh=wrap_soc_kwh, soc_end_pct=wrap_soc_pct,
    )
    hours = hours + [wrap_hour]
    x_labels = HOUR_LABELS + ["6 AM"]

    # Grid: positive = selling/exporting, negative = buying -- per the requested convention.
    # Battery: actual kWh held in the battery each hour (SOC% * total capacity), not
    # charge/discharge flow -- e.g. a 16kWh battery at 100% SOC plots as 16.
    series = [
        ([h.consumption_kwh for h in hours], SERIES_COLORS["Consumption"]),
        ([h.solar_kwh for h in hours], SERIES_COLORS["Solar/Harvest"]),
        ([h.grid_export_kwh - h.grid_purchase_kwh for h in hours], SERIES_COLORS["Grid"]),
        ([h.soc_end_pct / 100 * battery_total_kwh for h in hours], SERIES_COLORS["Battery"], True),
    ]
    return series, x_labels, hours
