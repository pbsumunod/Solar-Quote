import pytest

from logic.calculations import HOUR_LABELS
from logic.chart_series import series_for_result
from logic.simulation import hourly_solar_kwh, run_hourly_simulation


def _full_day_result(battery_total_kwh=10.0):
    harvest = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [5, 12, 25, 45, 70, 95, 95, 70, 45, 25, 12, 5])
    consumption = [1.5] * 24
    return run_hourly_simulation(
        hourly_consumption_kwh=consumption,
        hourly_solar_kwh_values=harvest,
        hour_labels=HOUR_LABELS,
        battery_total_kwh=battery_total_kwh,
        battery_dod_pct=80,
        battery_efficiency_pct=90,
        max_battery_charge_kw=5.0,
        max_battery_discharge_kw=5.0,
        grid_export_enabled=True,
        initial_soc_kwh=battery_total_kwh * 0.5,
    )


class TestSeriesForResult:
    def test_x_labels_wrap_around_to_6am(self):
        result = _full_day_result()
        _, x_labels, _ = series_for_result(result, 10.0)
        assert x_labels == HOUR_LABELS + ["6 AM"]

    def test_returns_four_series(self):
        result = _full_day_result()
        series, _, _ = series_for_result(result, 10.0)
        assert len(series) == 4

    def test_each_series_matches_wrapped_hour_count(self):
        result = _full_day_result()
        series, _, hours = series_for_result(result, 10.0)
        assert len(hours) == 25
        for values, *_rest in series:
            assert len(values) == 25

    def test_consumption_series_matches_hourly_consumption(self):
        result = _full_day_result()
        series, _, hours = series_for_result(result, 10.0)
        consumption_series = series[0][0]
        assert consumption_series == [h.consumption_kwh for h in hours]

    def test_grid_series_is_export_minus_purchase(self):
        result = _full_day_result()
        series, _, hours = series_for_result(result, 10.0)
        grid_series = series[2][0]
        expected = [h.grid_export_kwh - h.grid_purchase_kwh for h in hours]
        assert grid_series == pytest.approx(expected)

    def test_battery_series_is_soc_pct_times_capacity(self):
        battery_total_kwh = 10.0
        result = _full_day_result(battery_total_kwh)
        series, _, hours = series_for_result(result, battery_total_kwh)
        battery_series = series[3][0]
        expected = [h.soc_end_pct / 100 * battery_total_kwh for h in hours]
        assert battery_series == pytest.approx(expected)

    def test_wrap_hour_mirrors_first_hour_start_of_day(self):
        result = _full_day_result()
        _, _, hours = series_for_result(result, 10.0)
        first, wrap = hours[0], hours[-1]
        assert wrap.hour_label == "6 AM"
        assert wrap.consumption_kwh == pytest.approx(first.consumption_kwh)
        assert wrap.soc_start_kwh == pytest.approx(first.soc_start_kwh)
        assert wrap.soc_end_kwh == pytest.approx(first.soc_start_kwh)
