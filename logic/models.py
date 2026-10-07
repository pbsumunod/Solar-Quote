"""Data shapes for saved projects (Instruction.md Section 2, 37)."""

from dataclasses import dataclass
import json
import math


@dataclass
class Project:
    id: int | None = None
    client_name: str = ""
    project_location: str = ""
    contact_number: str = ""
    email: str = ""
    project_date: str = ""
    notes: str = ""
    monthly_kwh: float = 0.0
    daytime_ratio_pct: int = 70
    electricity_rate: float = 14.50
    country: str = "Philippines"  # mobile-only field, used to scale solar harvest by latitude
    peak_load_kw: float | None = None
    surge_load_kw: float | None = None
    storage_enabled: bool = True
    site_latitude: float | None = None
    site_longitude: float | None = None
    site_tilt_deg: float = 10.0
    site_azimuth_deg: float = 180.0
    site_shading_pct: float = 0.0

    def design_inputs(self) -> dict:
        return {name: getattr(self, name) for name in (
            "peak_load_kw", "surge_load_kw", "storage_enabled", "site_latitude",
            "site_longitude", "site_tilt_deg", "site_azimuth_deg", "site_shading_pct",
        )}

    @property
    def nighttime_ratio_pct(self) -> int:
        return 100 - self.daytime_ratio_pct

    def to_fields(self) -> dict:
        return {
            "client_name": self.client_name,
            "project_location": self.project_location,
            "contact_number": self.contact_number,
            "email": self.email,
            "project_date": self.project_date,
            "notes": self.notes,
            "monthly_kwh": self.monthly_kwh,
            "daytime_ratio_pct": self.daytime_ratio_pct,
            "electricity_rate": self.electricity_rate,
            "country": self.country,
            "design_inputs": json.dumps(self.design_inputs(), allow_nan=False),
        }

    @classmethod
    def from_row(cls, row) -> "Project":
        try:
            inputs = json.loads(row["design_inputs"]) if "design_inputs" in row.keys() else {}
            if not isinstance(inputs, dict):
                inputs = {}
        except (ValueError, TypeError):
            inputs = {}
        allowed = cls().design_inputs()
        clean = {}
        for key, value in inputs.items():
            if key not in allowed:
                continue
            if key == "storage_enabled":
                if isinstance(value, bool):
                    clean[key] = value
            elif value is None and allowed[key] is None:
                clean[key] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                clean[key] = float(value)
        inputs = clean
        return cls(
            id=row["id"],
            client_name=row["client_name"],
            project_location=row["project_location"],
            contact_number=row["contact_number"],
            email=row["email"],
            project_date=row["project_date"],
            notes=row["notes"],
            monthly_kwh=row["monthly_kwh"],
            daytime_ratio_pct=row["daytime_ratio_pct"],
            electricity_rate=row["electricity_rate"],
            country=row["country"] if "country" in row.keys() else "",
            **inputs,
        )
