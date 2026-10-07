from logic.models import Project
import json


class TestProjectDefaults:
    def test_default_values(self):
        project = Project()
        assert project.id is None
        assert project.client_name == ""
        assert project.daytime_ratio_pct == 70
        assert project.electricity_rate == 14.50
        assert project.country == "Philippines"


class TestNighttimeRatioPct:
    def test_complements_daytime_ratio(self):
        project = Project(daytime_ratio_pct=65)
        assert project.nighttime_ratio_pct == 35

    def test_updates_when_daytime_ratio_changes(self):
        project = Project(daytime_ratio_pct=70)
        project.daytime_ratio_pct = 40
        assert project.nighttime_ratio_pct == 60


class TestToFields:
    def test_returns_expected_keys_and_values(self):
        project = Project(
            id=1, client_name="Jane Doe", project_location="Manila",
            contact_number="123", email="jane@example.com", project_date="2026-01-01",
            notes="note", monthly_kwh=300.0, daytime_ratio_pct=60,
            electricity_rate=12.0, country="Japan",
        )
        fields = project.to_fields()
        assert json.loads(fields.pop("design_inputs")) == project.design_inputs()
        assert "id" not in fields
        assert fields == {
            "client_name": "Jane Doe",
            "project_location": "Manila",
            "contact_number": "123",
            "email": "jane@example.com",
            "project_date": "2026-01-01",
            "notes": "note",
            "monthly_kwh": 300.0,
            "daytime_ratio_pct": 60,
            "electricity_rate": 12.0,
            "country": "Japan",
        }


class TestFromRow:
    def test_builds_project_from_mapping(self):
        row = {
            "id": 5, "client_name": "Jane Doe", "project_location": "Manila",
            "contact_number": "123", "email": "jane@example.com",
            "project_date": "2026-01-01", "notes": "note", "monthly_kwh": 300.0,
            "daytime_ratio_pct": 60, "electricity_rate": 12.0, "country": "Japan",
        }
        project = Project.from_row(row)
        assert project.id == 5
        assert project.client_name == "Jane Doe"
        assert project.country == "Japan"

    def test_missing_country_column_defaults_to_empty_string(self):
        row = {
            "id": 5, "client_name": "Jane Doe", "project_location": "Manila",
            "contact_number": "123", "email": "jane@example.com",
            "project_date": "2026-01-01", "notes": "note", "monthly_kwh": 300.0,
            "daytime_ratio_pct": 60, "electricity_rate": 12.0,
        }
        project = Project.from_row(row)
        assert project.country == ""


def test_design_inputs_restore_with_legacy_defaults():
    fields = Project(client_name="Design", peak_load_kw=2.1, storage_enabled=False, site_latitude=14.6,
                     site_longitude=121, site_shading_pct=15).to_fields()
    fields["id"] = 1
    restored = Project.from_row(fields)
    assert restored.peak_load_kw == 2.1
    assert restored.storage_enabled is False
    assert restored.site_shading_pct == 15
