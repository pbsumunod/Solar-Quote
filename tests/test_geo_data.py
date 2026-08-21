import math

import pytest

from logic.geo_data import latitude_for_country, solar_latitude_factor


class TestLatitudeForCountry:
    def test_known_country(self):
        assert latitude_for_country("Philippines") == pytest.approx(14.6)

    def test_unknown_country_returns_none(self):
        assert latitude_for_country("Atlantis") is None


class TestSolarLatitudeFactor:
    def test_equator_is_near_maximum(self):
        assert solar_latitude_factor(0.0) == pytest.approx(1.0)

    def test_matches_cosine_within_bounds(self):
        assert solar_latitude_factor(60.0) == pytest.approx(math.cos(math.radians(60.0)))

    def test_high_latitude_clamped_to_floor(self):
        assert solar_latitude_factor(90.0) == pytest.approx(0.35)

    def test_southern_hemisphere_uses_absolute_value(self):
        assert solar_latitude_factor(-45.0) == pytest.approx(solar_latitude_factor(45.0))

    def test_never_below_floor_or_above_one(self):
        for lat in (0.0, 15.0, 45.0, 75.0, 90.0, -90.0):
            factor = solar_latitude_factor(lat)
            assert 0.35 <= factor <= 1.0
