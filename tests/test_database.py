from db import database
from logic.models import Project
import pytest


def test_consume_first_launch_is_only_true_once(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()

    assert database.consume_first_launch() is True
    assert database.consume_first_launch() is False


def test_project_crud_and_quote_data_survive_reopen(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()
    fields = Project(client_name="María ☀", monthly_kwh=450).to_fields()
    fields["quote_data"] = '{"solar": {"peak_sun_hours": 5.5}}'
    project_id = database.create_project(fields)
    assert database.get_project(project_id)["quote_data"] == fields["quote_data"]
    fields["monthly_kwh"] = 500
    database.update_project(project_id, fields)
    copy_id = database.duplicate_project(project_id)
    assert database.get_project(copy_id)["client_name"] == "María ☀ (Copy)"
    database.delete_project(project_id)
    database.init_db()  # reopening the existing file must preserve the copy
    assert database.get_project(project_id) is None
    assert database.get_project(copy_id)["monthly_kwh"] == 500
    assert len(database.list_projects()) == 1


def test_update_missing_project_reports_failure(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()
    fields = Project(client_name="Missing", monthly_kwh=300).to_fields()
    with pytest.raises(LookupError):
        database.update_project(99999, fields)
