import json
import sqlite3

import pytest

from db import database
from logic.models import Project


def setup_database(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()


def test_project_backup_excludes_subscription_and_draft_settings(tmp_path):
    setup_database(tmp_path)
    database.create_project(Project(client_name="王明", monthly_kwh=120, peak_load_kw=1, storage_enabled=False).to_fields())
    database.set_tier("pro")
    database.set_setting("secret_purchase_token", "never-export-this")
    database.save_draft({"incomplete": True})
    target = tmp_path / "projects.json"
    database.export_projects(str(target))
    text = target.read_text(encoding="utf-8")
    assert "never-export-this" not in text
    assert "app_settings" not in text
    original = database.list_projects()[0]
    ids = database.import_projects(str(target))
    assert len(ids) == 1
    assert json.loads(database.get_project(ids[0])["design_inputs"]) == json.loads(original["design_inputs"])
    assert database.get_tier() == "pro"


def test_invalid_backup_is_atomic_and_preserves_existing_projects(tmp_path):
    setup_database(tmp_path)
    pid = database.create_project(Project(client_name="Existing", monthly_kwh=120).to_fields())
    valid = dict(database.get_project(pid))
    bad = dict(valid, monthly_kwh=-5)
    target = tmp_path / "bad.json"
    target.write_text(json.dumps({"format": "solarquote-projects", "version": 1, "projects": [valid, bad]}))
    with pytest.raises(ValueError):
        database.import_projects(str(target))
    assert database.count_projects() == 1


def test_legacy_database_migrates_without_losing_existing_quote(tmp_path):
    database.configure(str(tmp_path))
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("CREATE TABLE projects(id INTEGER PRIMARY KEY,client_name TEXT,project_location TEXT,contact_number TEXT,email TEXT,project_date TEXT,notes TEXT,monthly_kwh REAL,daytime_ratio_pct INTEGER,electricity_rate REAL,created_at TEXT,updated_at TEXT)")
    conn.execute("INSERT INTO projects VALUES(1,'Legacy','','','','','',120,70,14.5,'','')")
    conn.commit()
    conn.close()
    database.init_db()
    restored = Project.from_row(database.get_project(1))
    assert restored.client_name == "Legacy"
    assert restored.storage_enabled is True
    assert restored.peak_load_kw is None


def test_incomplete_raw_draft_survives_database_reopen(tmp_path):
    setup_database(tmp_path)
    draft = {"raw_fields": {"client": {"monthly_kwh_field": "."}}, "project_id": None}
    database.save_draft(draft)
    database.init_db()
    assert database.load_draft() == draft


@pytest.mark.parametrize("changes", [
    {"quote_data": '{"report": []}'},
    {"quote_data": '{"solar": {"monthly_peak_sun_hours": [5]}}'},
    {"design_inputs": '{"site_latitude": 100, "site_longitude": 121}'},
    {"design_inputs": '{"storage_enabled": "false"}'},
    {"client_name": ["Invalid"]},
])
def test_malformed_backup_inputs_fail_before_any_write(tmp_path, changes):
    setup_database(tmp_path)
    pid = database.create_project(Project(client_name="Original", monthly_kwh=120).to_fields())
    good = dict(database.get_project(pid))
    bad = dict(good, **changes)
    target = tmp_path / "bad-state.json"
    target.write_text(json.dumps({"format": "solarquote-projects", "version": 1, "projects": [good, bad]}))
    with pytest.raises(ValueError):
        database.import_projects(str(target))
    assert database.count_projects() == 1
