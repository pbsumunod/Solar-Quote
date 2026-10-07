import pytest

from logic.financial import build_projection_table, calculate_discounted_payback_years, future_rate, net_present_value, projection_sensitivity


def projection(**overrides):
    options = dict(system_cost=1000, base_rate=1, inflation_pct=0, annual_kwh_without_solar=1000,
                   annual_grid_purchase_kwh=200, annual_grid_export_kwh=0, export_rate=0,
                   export_enabled=False, maintenance_method="fixed", maintenance_pct=0,
                   maintenance_fixed=0, maintenance_inflation_pct=0, years=3)
    options.update(overrides)
    return build_projection_table(**options)


def test_degradation_reduces_displacement_and_replacement_restores_battery_age():
    rows = projection(battery_degradation_pct=10, annual_battery_discharge_kwh=400,
                      battery_replacement_years=2, battery_replacement_cost=300)
    assert [row.electricity_savings for row in rows] == pytest.approx([800, 760, 800])
    assert [row.replacement for row in rows] == [0, 0, 300]
    assert rows[-1].net_savings == 500


def test_panel_degradation_and_replacement_costs_change_cash_flow():
    rows = projection(pv_degradation_pct=10, inverter_replacement_years=2, inverter_replacement_cost=200)
    assert [row.electricity_savings for row in rows] == pytest.approx([800, 720, 648])
    assert rows[-1].cumulative_cash_flow == pytest.approx(-1000 + 800 + 720 + 648 - 200)


def test_discounted_cash_flow_uses_year_end_discounting():
    rows = projection(discount_rate_pct=10)
    expected = -1000 + sum(800 / 1.1 ** year for year in range(1, 4))
    assert net_present_value(rows, 1000) == pytest.approx(expected)
    assert calculate_discounted_payback_years(rows, 1000) > 1.25


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), 1e20, -100])
def test_growth_values_are_rejected_before_overflow(rate):
    with pytest.raises(ValueError):
        future_rate(14.5, rate, 25)


def test_no_solar_produces_zero_savings_before_expenses():
    rows = projection(annual_grid_purchase_kwh=1000, pv_degradation_pct=0.5)
    assert all(row.electricity_savings == 0 for row in rows)


def test_sensitivity_changes_one_assumption_without_mutating_inputs():
    inputs = dict(system_cost=1000, base_rate=1, inflation_pct=0, annual_kwh_without_solar=1000,
                  annual_grid_purchase_kwh=100, annual_grid_export_kwh=20, export_rate=0.5,
                  export_enabled=True, maintenance_method="fixed", maintenance_pct=0,
                  maintenance_fixed=0, maintenance_inflation_pct=0, years=3, discount_rate_pct=6)
    saved = dict(inputs)
    cases = {case["scenario"]: case for case in projection_sensitivity(**inputs)}
    assert inputs == saved
    base = cases["Base assumptions"]
    assert cases["Installed cost +10%"]["npv"] < base["npv"] < cases["Installed cost -10%"]["npv"]
    assert cases["Retail tariff -10%"]["npv"] < base["npv"] < cases["Retail tariff +10%"]["npv"]
    assert cases["Solar yield -20%"]["npv"] < base["npv"] < cases["Solar yield +20%"]["npv"]
    assert cases["Solar yield +20%"]["annual_grid_purchase_kwh"] == 0
