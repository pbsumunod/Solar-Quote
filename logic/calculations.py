"""Consumption, solar, battery, and inverter sizing calculations (Instruction.md Sections 4-13)."""

# Legacy tier helpers remain available to callers. Automatic compatible inverter
# and battery module selection lives in logic.equipment; DC PV is sized separately.
BATTERY_CAPACITY_TIERS_KWH = [2.56, 5.12, 10.24, 15.36, 20.48, 30.72, 40.96, 61.44, 122.88]
INVERTER_KW_TIERS = [1.0, 3.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 18.0, 20.0, 25.0, 30.0, 40.0, 50.0]

HOURS_ORDER = list(range(6, 24)) + list(range(0, 6))
DAYTIME_HOUR_COUNT = 12  # first 12 entries below are 6 AM - 5 PM, the rest are 6 PM - 5 AM


def format_hour_label(hour_24: int) -> str:
    if hour_24 == 0:
        return "12 AM"
    if hour_24 < 12:
        return f"{hour_24} AM"
    if hour_24 == 12:
        return "12 PM"
    return f"{hour_24 - 12} PM"


HOUR_LABELS = [format_hour_label(h) for h in HOURS_ORDER]


def is_daytime_index(index: int) -> bool:
    return index < DAYTIME_HOUR_COUNT


def daily_consumption_kwh(monthly_kwh: float) -> float:
    """Average daily consumption on the same 365-day basis used by annual ROI."""
    return monthly_kwh * 12 / 365


def split_day_night_kwh(daily_kwh: float, daytime_pct: int) -> tuple[float, float]:
    """Section 4: split daily consumption by the day/night ratio."""
    day_kwh = daily_kwh * daytime_pct / 100
    night_kwh = daily_kwh - day_kwh
    return day_kwh, night_kwh


def default_hourly_percentages(daytime_pct: int) -> list[float]:
    """Section 5: distribute daytime/nighttime consumption evenly across their 12 hours each."""
    nighttime_pct = 100 - daytime_pct
    day_hour_pct = daytime_pct / DAYTIME_HOUR_COUNT
    night_hour_pct = nighttime_pct / DAYTIME_HOUR_COUNT
    return [day_hour_pct] * DAYTIME_HOUR_COUNT + [night_hour_pct] * (24 - DAYTIME_HOUR_COUNT)


def hourly_kwh_from_percentages(monthly_kwh: float, hourly_pct: list[float]) -> list[float]:
    daily_kwh = daily_consumption_kwh(monthly_kwh)
    return [daily_kwh * pct / 100 for pct in hourly_pct]


def required_solar_kw(daily_kwh: float, peak_sun_hours: float, system_efficiency_pct: float) -> float:
    """Section 8: Daily Energy Requirement / Peak Sun Hours / System Efficiency."""
    if peak_sun_hours <= 0 or system_efficiency_pct <= 0:
        return 0.0
    return daily_kwh / peak_sun_hours / (system_efficiency_pct / 100)


def parse_standard_sizes(text: str) -> list[float]:
    """Parse a comma-separated list of standard sizes (e.g. from an editable text field)."""
    sizes = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            sizes.append(float(token))
        except ValueError:
            continue
    return sizes


def round_up_to_standard_size(required_kw: float, standard_sizes: list[float]) -> float | None:
    """Return a tier that meets demand, or None when the catalog cannot meet it."""
    sizes = sorted(s for s in standard_sizes if s > 0)
    if not sizes:
        return None
    for size in sizes:
        if size >= required_kw:
            return size
    return None


def required_battery_kwh(nighttime_kwh: float, battery_dod_pct: float, battery_efficiency_pct: float) -> float:
    """Section 10: Nighttime Energy / Battery DOD / Battery Efficiency."""
    if battery_dod_pct <= 0 or battery_efficiency_pct <= 0:
        return 0.0
    return nighttime_kwh / (battery_dod_pct / 100) / (battery_efficiency_pct / 100)


def battery_usable_capacity_kwh(total_capacity_kwh: float, battery_dod_pct: float) -> float:
    """Section 11: Total Battery Capacity x DOD."""
    return total_capacity_kwh * battery_dod_pct / 100


def required_inverter_kw(peak_hourly_kwh: float, pv_capacity_kw: float) -> float:
    """Section 12: no single fixed formula is given in the spec (it lists peak load, PV
    capacity, and battery charging requirements as factors). This approximates the
    requirement as the larger of peak hourly load and PV capacity, since the inverter must
    be able to handle both -- shown via SHOW CALCULATION so the installer can judge and
    adjust the final selection.
    """
    return max(peak_hourly_kwh, pv_capacity_kw)
