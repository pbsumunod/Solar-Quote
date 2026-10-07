import pytest

from logic.calculations import (
    DAYTIME_HOUR_COUNT,
    HOUR_LABELS,
    HOURS_ORDER,
    daily_consumption_kwh,
    default_hourly_percentages,
    format_hour_label,
    hourly_kwh_from_percentages,
    is_daytime_index,
    parse_standard_sizes,
    required_battery_kwh,
    required_inverter_kw,
    required_solar_kw,
    round_up_to_standard_size,
    battery_usable_capacity_kwh,
    split_day_night_kwh,
)


class TestFormatHourLabel:
    def test_midnight(self):
        assert format_hour_label(0) == "12 AM"

    def test_morning(self):
        assert format_hour_label(1) == "1 AM"
        assert format_hour_label(11) == "11 AM"

    def test_noon(self):
        assert format_hour_label(12) == "12 PM"

    def test_afternoon_evening(self):
        assert format_hour_label(13) == "1 PM"
        assert format_hour_label(23) == "11 PM"


class TestHourLabels:
    def test_length(self):
        assert len(HOURS_ORDER) == 24
        assert len(HOUR_LABELS) == 24

    def test_starts_at_6am_ends_at_5am(self):
        assert HOUR_LABELS[0] == "6 AM"
        assert HOUR_LABELS[11] == "5 PM"
        assert HOUR_LABELS[12] == "6 PM"
        assert HOUR_LABELS[-1] == "5 AM"


class TestIsDaytimeIndex:
    def test_last_daytime_index(self):
        assert is_daytime_index(DAYTIME_HOUR_COUNT - 1) is True

    def test_first_nighttime_index(self):
        assert is_daytime_index(DAYTIME_HOUR_COUNT) is False


class TestDailyConsumption:
    def test_daily_consumption_annualizes_to_twelve_months(self):
        assert daily_consumption_kwh(300) * 365 == pytest.approx(300 * 12)


class TestSplitDayNight:
    def test_splits_by_percentage(self):
        day, night = split_day_night_kwh(10.0, 70)
        assert day == pytest.approx(7.0)
        assert night == pytest.approx(3.0)

    def test_day_and_night_sum_to_total(self):
        day, night = split_day_night_kwh(12.5, 35)
        assert day + night == pytest.approx(12.5)


class TestDefaultHourlyPercentages:
    def test_length_and_split(self):
        pct = default_hourly_percentages(70)
        assert len(pct) == 24
        assert pct[0] == pytest.approx(70 / 12)
        assert pct[-1] == pytest.approx(30 / 12)

    def test_sums_to_100(self):
        pct = default_hourly_percentages(40)
        assert sum(pct) == pytest.approx(100.0)


class TestHourlyKwhFromPercentages:
    def test_sums_to_daily_total(self):
        pct = default_hourly_percentages(70)
        hourly = hourly_kwh_from_percentages(300, pct)
        assert len(hourly) == 24
        assert sum(hourly) == pytest.approx(daily_consumption_kwh(300))

    def test_respects_day_night_ratio(self):
        pct = default_hourly_percentages(70)
        hourly = hourly_kwh_from_percentages(300, pct)
        day_total = sum(hourly[:12])
        night_total = sum(hourly[12:])
        assert day_total == pytest.approx(night_total * 70 / 30)


class TestRequiredSolarKw:
    def test_normal_case(self):
        assert required_solar_kw(10.0, 5.0, 80) == pytest.approx(2.5)

    def test_zero_peak_sun_hours_returns_zero(self):
        assert required_solar_kw(10.0, 0.0, 80) == 0.0

    def test_zero_efficiency_returns_zero(self):
        assert required_solar_kw(10.0, 5.0, 0) == 0.0

    def test_negative_peak_sun_hours_returns_zero(self):
        assert required_solar_kw(10.0, -1.0, 80) == 0.0


class TestParseStandardSizes:
    def test_parses_valid_comma_list(self):
        assert parse_standard_sizes("5, 10, 20.5") == [5.0, 10.0, 20.5]

    def test_skips_blank_and_invalid_tokens(self):
        assert parse_standard_sizes("5, , abc, 10") == [5.0, 10.0]

    def test_empty_string_returns_empty_list(self):
        assert parse_standard_sizes("") == []


class TestRoundUpToStandardSize:
    def test_rounds_up_to_next_tier(self):
        assert round_up_to_standard_size(7, [5, 10, 16, 32]) == 10

    def test_exact_match_returned(self):
        assert round_up_to_standard_size(10, [5, 10, 16, 32]) == 10

    def test_exceeds_max_does_not_substitute_undersized_equipment(self):
        assert round_up_to_standard_size(50, [5, 10, 16, 32]) is None

    def test_no_sizes_returns_none(self):
        assert round_up_to_standard_size(7, []) is None

    def test_only_nonpositive_sizes_returns_none(self):
        assert round_up_to_standard_size(7, [-5, 0]) is None


class TestRequiredBatteryKwh:
    def test_normal_case(self):
        assert required_battery_kwh(6.0, 80, 90) == pytest.approx(6.0 / 0.8 / 0.9)

    def test_zero_dod_returns_zero(self):
        assert required_battery_kwh(6.0, 0, 90) == 0.0

    def test_zero_efficiency_returns_zero(self):
        assert required_battery_kwh(6.0, 80, 0) == 0.0


class TestBatteryUsableCapacity:
    def test_normal_case(self):
        assert battery_usable_capacity_kwh(10.0, 80) == pytest.approx(8.0)


class TestRequiredInverterKw:
    def test_peak_load_dominates(self):
        assert required_inverter_kw(10.0, 8.0) == 10.0

    def test_pv_capacity_dominates(self):
        assert required_inverter_kw(5.0, 8.0) == 8.0
