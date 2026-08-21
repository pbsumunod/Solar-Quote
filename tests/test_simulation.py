import pytest

from logic.simulation import (
    DEFAULT_SOLAR_HARVEST_PCT,
    base_daily_production_kwh,
    default_solar_harvest_pct,
    hourly_solar_kwh,
    run_hourly_simulation,
    run_steady_state_simulation,
)


class TestDefaultSolarHarvestPct:
    def test_returns_a_copy_not_the_shared_constant(self):
        harvest = default_solar_harvest_pct()
        harvest.append(999)
        assert len(DEFAULT_SOLAR_HARVEST_PCT) == 12


class TestBaseDailyProductionKwh:
    def test_normal_case(self):
        assert base_daily_production_kwh(10.0, 5.0, 80) == pytest.approx(40.0)


class TestHourlySolarKwh:
    def test_length_and_night_hours_are_zero(self):
        result = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [10.0] * 12)
        assert len(result) == 24
        assert result[12:] == [0.0] * 12

    def test_daytime_sums_to_total_daily_kwh(self):
        result = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [10.0] * 12)
        assert sum(result[:12]) == pytest.approx(40.0)

    def test_weather_factor_scales_total(self):
        sunny = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [10.0] * 12)
        cloudy = hourly_solar_kwh(10.0, 5.0, 80, 60.0, [10.0] * 12)
        assert sum(cloudy[:12]) == pytest.approx(sum(sunny[:12]) * 0.6)

    def test_shape_is_normalized_against_total(self):
        result = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [5, 12, 25, 45, 70, 95, 95, 70, 45, 25, 12, 5])
        assert sum(result) == pytest.approx(40.0)
        # peak hours (index 5 and 6, value 95) should carry equal, largest shares
        assert result[5] == pytest.approx(result[6])
        assert result[5] == max(result)

    def test_zero_shape_total_returns_all_zero_daytime(self):
        result = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [0.0] * 12)
        assert result[:12] == [0.0] * 12


class TestRunHourlySimulation:
    def test_solar_surplus_charges_battery(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[2.0],
            hourly_solar_kwh_values=[5.0],
            hour_labels=["H1"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=False,
            initial_soc_kwh=0.0,
        )
        hour = result.hours[0]
        assert hour.solar_to_load_kwh == pytest.approx(2.0)
        assert hour.battery_charge_kwh == pytest.approx(3.0)
        assert hour.soc_end_kwh == pytest.approx(3.0)
        assert hour.grid_export_kwh == 0.0
        assert hour.curtailed_kwh == 0.0

    def test_excess_solar_curtailed_when_export_disabled_and_battery_full(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[0.0],
            hourly_solar_kwh_values=[5.0],
            hour_labels=["H1"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=False,
            initial_soc_kwh=10.0,
        )
        hour = result.hours[0]
        assert hour.battery_charge_kwh == pytest.approx(0.0)
        assert hour.curtailed_kwh == pytest.approx(5.0)
        assert hour.grid_export_kwh == 0.0

    def test_excess_solar_exported_when_enabled(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[0.0],
            hourly_solar_kwh_values=[5.0],
            hour_labels=["H1"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=True,
            initial_soc_kwh=10.0,
        )
        hour = result.hours[0]
        assert hour.grid_export_kwh == pytest.approx(5.0)
        assert hour.curtailed_kwh == pytest.approx(0.0)

    def test_deficit_draws_battery_then_grid(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[6.0],
            hourly_solar_kwh_values=[0.0],
            hour_labels=["H1"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=False,
            initial_soc_kwh=3.0,
        )
        hour = result.hours[0]
        # only 3 kWh available and max discharge is 5kW, so battery gives 3, grid covers the rest
        assert hour.battery_discharge_kwh == pytest.approx(3.0)
        assert hour.grid_purchase_kwh == pytest.approx(3.0)
        assert hour.soc_end_kwh == pytest.approx(0.0)

    def test_two_hour_sequence_carries_soc_forward(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[2.0, 6.0],
            hourly_solar_kwh_values=[5.0, 0.0],
            hour_labels=["H1", "H2"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=False,
            initial_soc_kwh=0.0,
        )
        h1, h2 = result.hours
        assert h1.soc_end_kwh == pytest.approx(3.0)
        assert h2.soc_start_kwh == pytest.approx(3.0)
        assert h2.battery_discharge_kwh == pytest.approx(3.0)
        assert h2.grid_purchase_kwh == pytest.approx(3.0)
        assert h2.soc_end_kwh == pytest.approx(0.0)

    def test_battery_efficiency_loss_applied_on_discharge(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[4.0],
            hourly_solar_kwh_values=[0.0],
            hour_labels=["H1"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=50,
            max_battery_charge_kw=10.0,
            max_battery_discharge_kw=10.0,
            grid_export_enabled=False,
            initial_soc_kwh=10.0,
        )
        hour = result.hours[0]
        # delivering 4 kWh to load at 50% efficiency draws 8 kWh from SOC
        assert hour.battery_discharge_kwh == pytest.approx(4.0)
        assert hour.grid_purchase_kwh == pytest.approx(0.0)
        assert hour.soc_end_kwh == pytest.approx(2.0)

    def test_totals_are_accumulated_across_hours(self):
        result = run_hourly_simulation(
            hourly_consumption_kwh=[2.0, 6.0],
            hourly_solar_kwh_values=[5.0, 0.0],
            hour_labels=["H1", "H2"],
            battery_total_kwh=10.0,
            battery_dod_pct=100,
            battery_efficiency_pct=100,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=False,
            initial_soc_kwh=0.0,
        )
        assert result.total_consumption_kwh == pytest.approx(8.0)
        assert result.total_solar_kwh == pytest.approx(5.0)
        assert result.total_grid_purchase_kwh == pytest.approx(3.0)


class TestRunSteadyStateSimulation:
    def test_ending_soc_converges_to_starting_soc(self):
        harvest = hourly_solar_kwh(10.0, 5.0, 80, 100.0, [5, 12, 25, 45, 70, 95, 95, 70, 45, 25, 12, 5])
        consumption = [1.0] * 24
        result = run_steady_state_simulation(
            hourly_consumption_kwh=consumption,
            hourly_solar_kwh_values=harvest,
            hour_labels=[str(i) for i in range(24)],
            battery_total_kwh=10.0,
            battery_dod_pct=80,
            battery_efficiency_pct=90,
            max_battery_charge_kw=5.0,
            max_battery_discharge_kw=5.0,
            grid_export_enabled=True,
        )
        first_soc = result.hours[0].soc_start_kwh
        last_soc = result.hours[-1].soc_end_kwh
        assert last_soc == pytest.approx(first_soc, abs=0.01)
