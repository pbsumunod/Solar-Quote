import copy

import pytest

from logic.models import Project
from logic.solar_assumptions import normalized_resource_state, resource_matches_project


def _saved_resource():
    return dict(peak_sun_hours=4.5, resource_source="NASA POWER roof estimate",
                resource_is_all_sky=True, monthly_peak_sun_hours=[4.5]*12,
                resource_coordinates=[14.6, 121.0],
                resource_metadata=dict(latitude=14.6, longitude=121.0, tilt_deg=10,
                                       azimuth_deg=180, shading_pct=5,
                                       fetched_at="2026-10-06T00:00:00+00:00",
                                       model="Isotropic roof estimate", cached=True))


def _project():
    return Project(site_latitude=14.6, site_longitude=121.0,
                   site_tilt_deg=10, site_azimuth_deg=180, site_shading_pct=5)


def test_saved_resource_normalizes_and_retains_site_model_and_timestamp():
    result = normalized_resource_state(_saved_resource())
    assert result["resource_is_all_sky"]
    assert result["resource_coordinates"] == (14.6, 121)
    assert result["resource_metadata"]["fetched_at"]
    assert result["resource_metadata"]["model"] == "Isotropic roof estimate"
    assert resource_matches_project(result["resource_metadata"], _project())


@pytest.mark.parametrize("field", ["site_latitude", "site_longitude", "site_tilt_deg",
                                   "site_azimuth_deg", "site_shading_pct"])
def test_any_site_or_roof_change_invalidates_imported_resource(field):
    p = _project()
    setattr(p, field, getattr(p, field) + 0.1)
    assert not resource_matches_project(_saved_resource()["resource_metadata"], p)


@pytest.mark.parametrize("key, value", [
    ("monthly_peak_sun_hours", "invalid"),
    ("monthly_peak_sun_hours", [4.5]*11),
    ("monthly_peak_sun_hours", [4.5]*11 + [float("nan")]),
    ("monthly_peak_sun_hours", [25]*12),
    ("monthly_peak_sun_hours", [3]*12),
    ("resource_metadata", "invalid"),
    ("resource_metadata", {}),
    ("resource_metadata", {"latitude": float("inf")}),
    ("resource_source", None),
    ("peak_sun_hours", "invalid"),
])
def test_malformed_saved_resource_is_cleared_without_crashing(key, value):
    data = _saved_resource()
    data[key] = value
    result = normalized_resource_state(data)
    assert not result["resource_is_all_sky"]
    assert result["peak_sun_hours"] == 4.5
    assert result["monthly_peak_sun_hours"] == []
    assert result["resource_metadata"] == {}
    assert "cleared" in result["resource_warning"]


def test_manual_assumptions_ignore_malformed_unused_resource_fields():
    result = normalized_resource_state(dict(peak_sun_hours="5.25", resource_is_all_sky=False,
                                           resource_metadata=123, monthly_peak_sun_hours="bad"))
    assert result["peak_sun_hours"] == 5.25
    assert not result["resource_is_all_sky"]
    assert result["monthly_peak_sun_hours"] == []


def test_missing_site_coordinates_cannot_match_previous_resource():
    assert not resource_matches_project(_saved_resource()["resource_metadata"], Project())


def test_saved_unknown_nested_metadata_is_not_used_in_live_calculations():
    data = copy.deepcopy(_saved_resource())
    data["resource_metadata"]["untrusted"] = {"x": float("nan")}
    result = normalized_resource_state(data)
    assert result["resource_is_all_sky"]
    assert "untrusted" not in result["resource_metadata"]
