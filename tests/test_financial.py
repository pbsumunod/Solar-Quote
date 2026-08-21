from types import SimpleNamespace

import pytest

from logic.financial import (
    annual_electricity_cost_without_solar,
    annual_grid_cost_with_solar,
    blended_annual_kwh,
    build_projection_table,
    calculate_payback_years,
    future_rate,
    maintenance_cost_for_year,
    net_benefit,
    roi_percent,
    total_electricity_savings,
)


class TestBlendedAnnualKwh:
    def test_weights_and_annualizes(self):
        scenario_results = {
            "Sunny": SimpleNamespace(total_solar_kwh=20.0),
            "Cloudy": SimpleNamespace(total_solar_kwh=10.0),
            "Rainy": SimpleNamespace(total_solar_kwh=5.0),
        }
        weather_mix = {"Sunny": 50, "Cloudy": 30, "Rainy": 20}
        result = blended_annual_kwh(scenario_results, weather_mix, "total_solar_kwh")
        expected = (20 * 0.5 + 10 * 0.3 + 5 * 0.2) * 365
        assert result == pytest.approx(expected)

    def test_missing_scenario_is_skipped(self):
        scenario_results = {"Sunny": SimpleNamespace(total_solar_kwh=20.0)}
        weather_mix = {"Sunny": 50, "Cloudy": 50}
        result = blended_annual_kwh(scenario_results, weather_mix, "total_solar_kwh")
        assert result == pytest.approx(20 * 0.5 * 365)


class TestAnnualElectricityCost:
    def test_without_solar(self):
        assert annual_electricity_cost_without_solar(300, 14.5) == pytest.approx(300 * 12 * 14.5)


class TestAnnualGridCostWithSolar:
    def test_export_enabled_reduces_cost(self):
        cost = annual_grid_cost_with_solar(
            annual_grid_purchase_kwh=200, rate=10, annual_grid_export_kwh=50,
            export_rate=5, export_enabled=True,
        )
        assert cost == pytest.approx(200 * 10 - 50 * 5)

    def test_export_disabled_ignores_export(self):
        cost = annual_grid_cost_with_solar(
            annual_grid_purchase_kwh=200, rate=10, annual_grid_export_kwh=50,
            export_rate=5, export_enabled=False,
        )
        assert cost == pytest.approx(200 * 10)


class TestFutureRate:
    def test_year_one_is_base_rate(self):
        assert future_rate(10.0, 10, 1) == pytest.approx(10.0)

    def test_compounds_each_year(self):
        assert future_rate(10.0, 10, 2) == pytest.approx(11.0)
        assert future_rate(10.0, 10, 3) == pytest.approx(12.1)


class TestMaintenanceCostForYear:
    def test_percentage_method_compounds(self):
        year1 = maintenance_cost_for_year(100_000, "percentage", 1, 0, 5, 1)
        year2 = maintenance_cost_for_year(100_000, "percentage", 1, 0, 5, 2)
        assert year1 == pytest.approx(1000.0)
        assert year2 == pytest.approx(1050.0)

    def test_fixed_method_ignores_system_cost(self):
        cost = maintenance_cost_for_year(100_000, "fixed", 1, 2000, 0, 1)
        assert cost == pytest.approx(2000.0)

    def test_fixed_method_still_inflates(self):
        cost = maintenance_cost_for_year(100_000, "fixed", 1, 2000, 10, 2)
        assert cost == pytest.approx(2200.0)


def _flat_rows():
    # inflation and maintenance-inflation at 0 keeps every year identical,
    # which makes the expected numbers easy to hand-verify.
    return build_projection_table(
        system_cost=1000,
        base_rate=10,
        inflation_pct=0,
        annual_kwh_without_solar=1000,
        annual_grid_purchase_kwh=200,
        annual_grid_export_kwh=50,
        export_rate=5,
        export_enabled=True,
        maintenance_method="fixed",
        maintenance_pct=0,
        maintenance_fixed=50,
        maintenance_inflation_pct=0,
        years=3,
    )


class TestBuildProjectionTable:
    def test_row_count(self):
        rows = _flat_rows()
        assert len(rows) == 3
        assert [r.year for r in rows] == [1, 2, 3]

    def test_first_year_values(self):
        rows = _flat_rows()
        first = rows[0]
        assert first.grid_cost_without_solar == pytest.approx(10_000)
        assert first.grid_cost_with_solar == pytest.approx(1_750)
        assert first.electricity_savings == pytest.approx(8_250)
        assert first.maintenance == pytest.approx(50)
        assert first.net_savings == pytest.approx(8_200)
        assert first.cumulative_cash_flow == pytest.approx(-1000 + 8_200)

    def test_cumulative_cash_flow_accumulates(self):
        rows = _flat_rows()
        assert rows[-1].cumulative_cash_flow == pytest.approx(-1000 + 8_200 * 3)


class TestCalculatePaybackYears:
    def test_interpolates_within_payback_year(self):
        rows = _flat_rows()
        payback = calculate_payback_years(rows, 1000)
        assert payback == pytest.approx(1000 / 8_200)

    def test_never_recoups_returns_none(self):
        rows = build_projection_table(
            system_cost=100_000,
            base_rate=10,
            inflation_pct=0,
            annual_kwh_without_solar=100,
            annual_grid_purchase_kwh=100,
            annual_grid_export_kwh=0,
            export_rate=0,
            export_enabled=False,
            maintenance_method="fixed",
            maintenance_pct=0,
            maintenance_fixed=0,
            maintenance_inflation_pct=0,
            years=3,
        )
        assert calculate_payback_years(rows, 100_000) is None

    def test_negative_net_savings_in_payback_year_returns_none(self):
        rows = build_projection_table(
            system_cost=100,
            base_rate=10,
            inflation_pct=0,
            annual_kwh_without_solar=1000,
            annual_grid_purchase_kwh=100,
            annual_grid_export_kwh=0,
            export_rate=0,
            export_enabled=False,
            maintenance_method="fixed",
            maintenance_pct=0,
            maintenance_fixed=100_000,
            maintenance_inflation_pct=0,
            years=1,
        )
        assert calculate_payback_years(rows, 100) is None


class TestTotalElectricitySavings:
    def test_sums_across_years(self):
        rows = _flat_rows()
        assert total_electricity_savings(rows) == pytest.approx(8_250 * 3)


class TestNetBenefit:
    def test_returns_final_cumulative_cash_flow(self):
        rows = _flat_rows()
        assert net_benefit(rows, 1000) == pytest.approx(rows[-1].cumulative_cash_flow)

    def test_empty_rows_returns_negative_system_cost(self):
        assert net_benefit([], 1000) == -1000


class TestRoiPercent:
    def test_normal_case(self):
        assert roi_percent(2000, 1000) == pytest.approx(200.0)

    def test_zero_system_cost_returns_zero(self):
        assert roi_percent(2000, 0) == 0.0
