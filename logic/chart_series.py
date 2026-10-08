"""Shared hourly-chart series construction for a SimulationResult, used by both the
Simulation screen (live chart) and the Report screen (PowerPoint chart-slide export)
so the two always draw the exact same lines from the exact same data.
"""

from logic.calculations import HOUR_LABELS

SERIES_COLORS = {
    "Consumption": (0.80, 0.15, 0.15, 1),
    "Solar/Harvest": (0.95, 0.75, 0.05, 1),
    "Grid": (0.15, 0.42, 0.80, 1),
    "Battery": (0.15, 0.55, 0.25, 1),
}

# Deliberately darker/more saturated than SERIES_COLORS["Battery"] -- the DOD floor
# marker line needs to read as a distinct, emphasized reference even where the
# Battery curve itself dips down to meet it (same hue would visually merge).
DOD_FLOOR_COLOR = (0.02, 0.28, 0.08, 1)

# Used by both the ROI screen's live cash-flow chart and the Report screen's
# PDF/PowerPoint ROI chart export, so both draw the same colors.
CASH_FLOW_COLOR = (0.15, 0.42, 0.75, 1)
PAYBACK_COLOR = (0.42, 0.25, 0.65, 1)


def roi_chart_series(
    system_cost: float, projection_rows: list, payback_years: float | None,
) -> tuple[list[tuple], list[str], dict | None]:
    """Cumulative cash-flow series for the ROI screen's live chart and the
    Report screen's PDF/PowerPoint export -- both draw the exact same line."""
    x_labels = ["0"] + [str(row.year) for row in projection_rows]
    cumulative = [-system_cost] + [row.cumulative_cash_flow for row in projection_rows]
    vline = None
    if payback_years is not None:
        vline = {"x": payback_years, "label": f"Payback ({payback_years:.1f} yrs)", "color": PAYBACK_COLOR}
    return [(cumulative, CASH_FLOW_COLOR)], x_labels, vline


def series_for_result(result, battery_total_kwh: float) -> tuple[list[tuple], list[str], list]:
    hours = list(result.hours)
    # Each sample is an actual simulated hour. Repeating the first hour at the
    # right edge invented a second 6 AM reading and a false battery jump.
    x_labels = HOUR_LABELS[:len(hours)]

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
