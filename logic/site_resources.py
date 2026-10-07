"""Opt-in NASA POWER climatology with an offline cache and documented POA estimate.

Only coordinates are sent. Cooper declination and isotropic-sky transposition:
https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.solarposition.declination_cooper69.html
https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.isotropic.html
This monthly representative-day model is a planning approximation, not a roof survey.
"""

import calendar
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from network_utils import tls_context

MONTH_NAMES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
MONTH_DAYS = [calendar.monthrange(2025, month)[1] for month in range(1, 13)]


def plane_of_array_hours(ghi: float, diffuse: float, latitude: float, tilt: float,
                         azimuth: float, month: int, shading_pct: float = 0) -> float:
    values = (ghi, diffuse, latitude, tilt, azimuth, shading_pct)
    if not all(math.isfinite(v) for v in values) or not (0 <= diffuse <= ghi <= 24):
        raise ValueError("Invalid solar resource measurements.")
    if not (-90 <= latitude <= 90 and 0 <= tilt <= 90 and 0 <= azimuth <= 360 and 0 <= shading_pct <= 100 and 1 <= month <= 12):
        raise ValueError("Roof geometry or shading is out of range.")
    day = sum(MONTH_DAYS[:month - 1]) + 15
    declination = math.radians(23.45) * math.sin(2 * math.pi * (284 + day) / 365)
    phi, beta, gamma = map(math.radians, (latitude, tilt, azimuth))
    normal = (math.sin(beta) * math.sin(gamma), math.sin(beta) * math.cos(gamma), math.cos(beta))
    horizontal_sum = tilted_sum = 0.0
    for index in range(144):
        hour_angle = -math.pi + (index + 0.5) * 2 * math.pi / 144
        sun = (-math.cos(declination) * math.sin(hour_angle),
               math.cos(phi) * math.sin(declination) - math.sin(phi) * math.cos(declination) * math.cos(hour_angle),
               math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(declination) * math.cos(hour_angle))
        if sun[2] > 0:
            horizontal_sum += sun[2]
            tilted_sum += max(0.0, sum(a * b for a, b in zip(normal, sun)))
    beam_ratio = tilted_sum / horizontal_sum if horizontal_sum > 1e-9 else 0
    poa = (ghi - diffuse) * beam_ratio + diffuse * (1 + math.cos(beta)) / 2 + ghi * 0.2 * (1 - math.cos(beta)) / 2
    return max(0.0, min(24.0, poa * (1 - shading_pct / 100)))


def parse_resource(data: dict, latitude: float, longitude: float, tilt: float = 10,
                   azimuth: float = 180, shading_pct: float = 0) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Invalid NASA POWER response.")
    for parameter in ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_SW_DIFF"):
        metadata = data.get("parameters")
        details = metadata.get(parameter) if isinstance(metadata, dict) else None
        units = details.get("units") if isinstance(details, dict) else None
        if units != "kW-hr/m^2/day":
            raise ValueError("Unexpected NASA POWER solar-resource units.")
    try:
        parameters = data["properties"]["parameter"]
        monthly = [plane_of_array_hours(float(parameters["ALLSKY_SFC_SW_DWN"][name]),
                   float(parameters["ALLSKY_SFC_SW_DIFF"][name]), latitude, tilt, azimuth, month, shading_pct)
                   for month, name in enumerate(MONTH_NAMES, 1)]
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("NASA POWER response lacks valid monthly solar measurements.") from exc
    return {"source": "NASA POWER all-sky climatology + isotropic roof estimate",
            "latitude": latitude, "longitude": longitude, "tilt_deg": tilt,
            "azimuth_deg": azimuth, "shading_pct": shading_pct,
            "monthly_peak_sun_hours": monthly,
            "annual_peak_sun_hours": sum(v * days for v, days in zip(monthly, MONTH_DAYS)) / 365,
            "fetched_at": data.get("solarquote_fetched_at", "unknown"),
            "model": "Monthly representative-day Cooper declination, isotropic diffuse sky, 0.2 albedo; supplied shading percentage."}


def load_solar_resource(latitude: float, longitude: float, cache_dir: str, *, tilt: float = 10,
                        azimuth: float = 180, shading_pct: float = 0) -> dict:
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Invalid site coordinates.")
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    cached_path = directory / f"power-v1-{latitude:.5f}-{longitude:.5f}.json"
    cached = None
    try:
        cached = json.loads(cached_path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(cached["solarquote_fetched_at"])
        if 0 <= (datetime.now(timezone.utc) - fetched).total_seconds() < 90 * 86400:
            result = parse_resource(cached, latitude, longitude, tilt, azimuth, shading_pct)
            result["cached"] = True
            return result
    except (OSError, ValueError, TypeError, KeyError):
        cached = None
    query = urlencode({"parameters": "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DIFF", "community": "RE",
                       "latitude": latitude, "longitude": longitude, "format": "JSON"})
    try:
        with urlopen("https://power.larc.nasa.gov/api/temporal/climatology/point?" + query, timeout=15, context=tls_context()) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError("Solar resource response is too large.")
            data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid NASA POWER response.")
        data["solarquote_fetched_at"] = datetime.now(timezone.utc).isoformat()
        result = parse_resource(data, latitude, longitude, tilt, azimuth, shading_pct)
        temporary = cached_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
        os.replace(temporary, cached_path)
        result["cached"] = False
        return result
    except (OSError, ValueError, KeyError):
        if cached is None:
            raise
        result = parse_resource(cached, latitude, longitude, tilt, azimuth, shading_pct)
        result["cached"] = True
        result["source"] += " (offline cached data)"
        return result
