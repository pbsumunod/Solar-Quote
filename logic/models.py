"""Data shapes for saved projects (Instruction.md Section 2, 37)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Project:
    id: Optional[int] = None
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
        }

    @classmethod
    def from_row(cls, row) -> "Project":
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
        )
