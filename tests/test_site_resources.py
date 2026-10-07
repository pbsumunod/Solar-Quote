import json

import pytest

from logic.site_resources import MONTH_NAMES, parse_resource, plane_of_array_hours, load_solar_resource


def test_horizontal_surface_preserves_radiation_and_shading_reduces_it():
    assert plane_of_array_hours(5, 2, 14.6, 0, 180, 1) == pytest.approx(5)
    assert plane_of_array_hours(5, 2, 14.6, 0, 180, 1, 20) == pytest.approx(4)


def test_roof_direction_affects_winter_resource():
    south = plane_of_array_hours(5, 2, 14.6, 45, 180, 1)
    north = plane_of_array_hours(5, 2, 14.6, 45, 0, 1)
    assert south > north


def test_cache_remains_available_without_network(tmp_path, monkeypatch):
    data = {"parameters": {name: {"units": "kW-hr/m^2/day"} for name in ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_SW_DIFF")},
            "properties": {"parameter": {"ALLSKY_SFC_SW_DWN": dict.fromkeys(MONTH_NAMES, 5),
                                          "ALLSKY_SFC_SW_DIFF": dict.fromkeys(MONTH_NAMES, 2)}},
            "solarquote_fetched_at": "2020-01-01T00:00:00+00:00"}
    (tmp_path / "power-v1-14.60000-121.00000.json").write_text(json.dumps(data), encoding="utf-8")
    def offline(*_args, **_kwargs):
        raise OSError("offline")
    monkeypatch.setattr("logic.site_resources.urlopen", offline)
    result = load_solar_resource(14.6, 121, str(tmp_path), tilt=0)
    assert result["annual_peak_sun_hours"] == pytest.approx(5)
    assert result["cached"] is True


def test_bad_units_are_rejected():
    with pytest.raises(ValueError, match="units"):
        parse_resource({}, 14.6, 121)


@pytest.mark.parametrize("data", [None, [], {"parameters": None}, {"parameters": {"ALLSKY_SFC_SW_DWN": []}}])
def test_malformed_remote_resource_fails_as_validation_error(data):
    with pytest.raises(ValueError):
        parse_resource(data, 14.6, 121)
