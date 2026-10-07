"""Normalize saved resource context and detect stale site/roof assumptions."""

import math

MANUAL_RESOURCE_SOURCE = "Manual peak sun hours (planning estimate)"
DEFAULT_PEAK_SUN_HOURS = 4.5
RESOURCE_SITE_KEYS = (
    ("latitude", "site_latitude", -90, 90),
    ("longitude", "site_longitude", -180, 180),
    ("tilt_deg", "site_tilt_deg", 0, 90),
    ("azimuth_deg", "site_azimuth_deg", 0, 360),
    ("shading_pct", "site_shading_pct", 0, 100),
)


def _number(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def normalized_resource_state(data: dict) -> dict:
    """Invalid imported data becomes an explicit manual planning assumption."""
    if not isinstance(data, dict):
        data = {}
    psh = _number(data.get("peak_sun_hours", DEFAULT_PEAK_SUN_HOURS), 0, 24)
    result = dict(peak_sun_hours=DEFAULT_PEAK_SUN_HOURS if psh is None else psh,
                  resource_source=MANUAL_RESOURCE_SOURCE, resource_is_all_sky=False,
                  monthly_peak_sun_hours=[], resource_coordinates=None,
                  resource_metadata={}, resource_warning="")
    if data.get("resource_is_all_sky") is not True:
        if isinstance(data.get("resource_warning"), str):
            result["resource_warning"] = data["resource_warning"]
        return result
    monthly = data.get("monthly_peak_sun_hours")
    metadata = data.get("resource_metadata")
    source = data.get("resource_source")
    valid = (isinstance(monthly, (list, tuple)) and len(monthly) == 12 and
             isinstance(metadata, dict) and isinstance(source, str) and bool(source.strip()) and
             psh is not None and psh > 0)
    monthly_numbers = [_number(v, 0, 24) for v in monthly] if isinstance(monthly, (list, tuple)) else []
    clean_metadata = {}
    if isinstance(metadata, dict):
        for key, _attr, low, high in RESOURCE_SITE_KEYS:
            clean_metadata[key] = _number(metadata.get(key), low, high)
        for key in ("source", "model", "fetched_at"):
            value = metadata.get(key)
            if isinstance(value, str):
                clean_metadata[key] = value
        if isinstance(metadata.get("cached"), bool):
            clean_metadata["cached"] = metadata["cached"]
    valid = valid and all(v is not None for v in monthly_numbers) and all(
        clean_metadata.get(key) is not None for key, *_ in RESOURCE_SITE_KEYS)
    if valid:
        month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        annual = sum(v * days for v, days in zip(monthly_numbers, month_days)) / 365
        valid = math.isclose(annual, psh, rel_tol=0, abs_tol=1e-5)
    if not valid:
        result["peak_sun_hours"] = DEFAULT_PEAK_SUN_HOURS
        result["resource_warning"] = "Saved solar resource was incomplete or invalid; cleared to the manual planning default. Reload the site resource."
        return result
    result.update(resource_source=source.strip(), resource_is_all_sky=True,
                  monthly_peak_sun_hours=monthly_numbers, resource_metadata=clean_metadata,
                  resource_coordinates=(clean_metadata["latitude"], clean_metadata["longitude"]))
    return result


def resource_matches_project(metadata: dict, project) -> bool:
    if not isinstance(metadata, dict):
        return False
    for key, attr, low, high in RESOURCE_SITE_KEYS:
        resource_value = _number(metadata.get(key), low, high)
        project_value = _number(getattr(project, attr, None), low, high)
        if resource_value is None or project_value is None or not math.isclose(
                resource_value, project_value, rel_tol=0, abs_tol=1e-7):
            return False
    return True
