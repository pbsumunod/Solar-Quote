"""Energy, power and sustainable-SOC regressions for quote/ROI projections."""

import pytest

from logic.simulation import hourly_solar_kwh, run_hourly_simulation, run_steady_state_simulation


def _run(load, solar, **overrides):
    inputs = dict(hourly_consumption_kwh=load, hourly_solar_kwh_values=solar,
                  hour_labels=[str(i) for i in range(len(load))], battery_total_kwh=10,
                  battery_dod_pct=80, battery_efficiency_pct=90,
                  max_battery_charge_kw=2, max_battery_discharge_kw=2,
                  grid_export_enabled=True, initial_soc_kwh=5,
                  inverter_rated_power_kw=3, inverter_efficiency_pct=95,
                  max_pv_input_kw=5, max_pv_charging_kw=1.5)
    inputs.update(overrides)
    return run_hourly_simulation(**inputs)


@pytest.mark.parametrize("export", [False, True])
def test_every_interval_and_total_conserve_energy_with_all_losses_and_limits(export):
    load = [0.1, 1.5, 7, 0, 3, 5, 0.2, 4]
    solar = [8, 4, 7, 0.3, 0, 0, 2, 0]
    r = _run(load, solar, grid_export_enabled=export)
    for h in r.hours:
        incoming = h.solar_kwh + h.soc_start_kwh + h.grid_purchase_kwh
        outgoing = (h.consumption_kwh + h.grid_export_kwh + h.curtailed_kwh +
                    h.conversion_loss_kwh + h.battery_loss_kwh + h.soc_end_kwh)
        assert incoming == pytest.approx(outgoing, abs=1e-10)
        assert h.solar_to_load_kwh + h.battery_discharge_kwh + h.grid_export_kwh <= 3 + 1e-10
        assert h.battery_charge_kwh <= 1.5 + 1e-10
        assert 2 - 1e-10 <= h.soc_end_kwh <= 10 + 1e-10
    assert (r.total_solar_kwh + r.hours[0].soc_start_kwh + r.total_grid_purchase_kwh) == pytest.approx(
        r.total_consumption_kwh + r.total_grid_export_kwh + r.total_curtailed_kwh +
        r.total_conversion_loss_kwh + r.total_battery_loss_kwh + r.hours[-1].soc_end_kwh)


def test_pv_input_and_ac_export_clipping_are_separate_from_conversion_loss():
    r = _run([0], [10], battery_total_kwh=0, initial_soc_kwh=0,
             max_battery_charge_kw=0, max_battery_discharge_kw=0,
             inverter_rated_power_kw=2, inverter_efficiency_pct=80,
             max_pv_input_kw=4)
    assert r.total_grid_export_kwh == pytest.approx(2)
    assert r.total_conversion_loss_kwh == pytest.approx(0.5)
    assert r.total_curtailed_kwh == pytest.approx(7.5)
    assert r.total_clipped_kwh == pytest.approx(7.5)


def test_solar_and_battery_share_inverter_output_limit():
    r = _run([5], [2], initial_soc_kwh=10, inverter_efficiency_pct=100,
             inverter_rated_power_kw=3, max_battery_discharge_kw=10)
    h = r.hours[0]
    assert h.solar_to_load_kwh == 2
    assert h.battery_discharge_kwh == 1
    assert h.grid_purchase_kwh == 2


def test_no_battery_zero_charger_limit_preserves_pv_load_supply():
    r = _run([1], [2], battery_total_kwh=0, initial_soc_kwh=0,
             max_battery_charge_kw=0, max_battery_discharge_kw=0,
             max_pv_charging_kw=0, grid_export_enabled=False)
    assert r.total_solar_to_load_kwh == 1
    assert r.total_grid_purchase_kwh == 0
    assert r.total_battery_charge_kwh == r.total_battery_discharge_kwh == 0


def test_battery_and_inverter_efficiencies_reduce_delivered_energy_once():
    r = _run([2, 5], [7, 0], battery_total_kwh=10, battery_dod_pct=100,
             initial_soc_kwh=0, inverter_efficiency_pct=80, battery_efficiency_pct=50,
             inverter_rated_power_kw=10, max_pv_input_kw=10, max_pv_charging_kw=10,
             max_battery_charge_kw=10, max_battery_discharge_kw=10,
             grid_export_enabled=False)
    assert r.hours[0].battery_charge_kwh == pytest.approx(4.5)
    assert r.hours[1].battery_discharge_kwh == pytest.approx(4.5 * 0.5 * 0.8)
    assert r.total_battery_loss_kwh == pytest.approx(2.25)


def test_slow_soc_drain_never_becomes_free_sustainable_battery_energy():
    r = run_steady_state_simulation([0.001] * 24, [0] * 24, [str(i) for i in range(24)],
                                    1000, 80, 90, 1, 1, False)
    assert r.total_battery_discharge_kwh == 0
    assert r.total_grid_purchase_kwh == pytest.approx(0.024)
    assert abs(r.soc_residual_kwh) <= 1e-7


def test_steady_cycle_converges_and_conserves_energy_with_conversion_loss():
    solar = hourly_solar_kwh(4, 4.5, 80, 60, [5,12,25,45,70,95,95,70,45,25,12,5])
    r = run_steady_state_simulation([0.4] * 24, solar, [str(i) for i in range(24)],
                                    8, 80, 90, 2, 2, True,
                                    inverter_rated_power_kw=3, inverter_efficiency_pct=95,
                                    max_pv_input_kw=5, max_pv_charging_kw=2)
    assert abs(r.soc_residual_kwh) <= 1e-7
    assert r.total_solar_kwh + r.total_grid_purchase_kwh == pytest.approx(
        r.total_consumption_kwh + r.total_grid_export_kwh + r.total_curtailed_kwh +
        r.total_conversion_loss_kwh + r.total_battery_loss_kwh, abs=1e-7)


@pytest.mark.parametrize("load, solar", [([-1], [0]), ([float("nan")], [0]), ([1], [float("inf")]),
                                       ([1e308, 1e308], [0, 0])])
def test_invalid_or_overflowing_energy_inputs_are_rejected(load, solar):
    with pytest.raises(ValueError):
        _run(load, solar)


@pytest.mark.parametrize("factor, shape", [(101, [1]*12), (-1, [1]*12), (100, [1]*11),
                                         (100, [-1]*12), (100, [1e308]*12)])
def test_invalid_solar_factors_and_harvest_shapes_are_rejected(factor, shape):
    with pytest.raises(ValueError):
        hourly_solar_kwh(1, 4.5, 80, factor, shape)
