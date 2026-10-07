"""Automatic planning design with traceable equipment ratings.

The catalog checks energy, power, current and the full battery voltage envelope.
This is a planning estimate, not a certification of BMS interoperability, PV string
voltages, grid approval, wiring or installation. Manufacturer revisions and the site
must be checked by the installer. The 1 kW profile is explicitly an estimated
assembly: its references are separate off-grid inverter/charge-controller products,
not a manufacturer-approved grid-connected hybrid system.
"""

from dataclasses import asdict, dataclass, field
import math

from logic.calculations import default_hourly_percentages, hourly_kwh_from_percentages
from logic.simulation import default_solar_harvest_pct

DEYE_SMALL = "https://www.deyeinverter.com/product/single-phase-low-voltage-hybrid-inverter/sun3-3-6-5-6ksg04lp1-3-6kw-single-phase.html"
DEYE_SMALL_MANUAL = "https://au.deyeinverter.com/deyeinverter/2024/08/13/rand/6698/instructions_sun-3-6k-sg04lp1-eu_240813_en.pdf"
DEYE_MID = "https://www.deyeinverter.com/product/single-phase-low-voltage-hybrid-inverter/hybrid-inverter-sun-3-610-ksg05lp1eusm2p-2740.html"
DEYE_LARGE = "https://www.deyeinverter.com/product/single-phase-low-voltage-hybrid-inverter/sun12-14-16-18ksg01lp1euam3p.html"
DEYE_HV = "https://www.deyeinverter.com/deyeinverter/2024/07/22/datasheet_sun-29.9-50k-sg01hp3-eu-bm4_240722_en.pdf"
DEYE_HV_MID = "https://www.deyeinverter.com/deyeinverter/2023/12/11/datasheet_sun-5-25k-sg01hp3-eu_231211_en.pdf"
VICTRON_INVERTER = "https://www.victronenergy.com/upload/documents/Datasheet-Inverter-VE.Direct-250VA-1200VA-EN.pdf"
VICTRON_MPPT = "https://www.victronenergy.com/upload/documents/Datasheet-SmartSolar-charge-controller-MPPT-100-30-%26-100-50-EN.pdf"
VICTRON_BATTERY = "https://www.victronenergy.com/media/pg/Lithium_NG_battery_25%2C6_V/en/technical-data.html"
DEYE_LV_BATTERY = "https://deyeess.com/product/se-g5-1/"
DEYE_HV_BATTERY = "https://deye.com/wp-content/uploads/2025/10/deye-ess-user-manual-bos-g-auen-v01-_20250929.pdf"
CATALOG_REVIEW_DATE = "2026-10-06"


@dataclass(frozen=True)
class InverterSpec:
    model: str
    rated_kw: float
    surge_kw: float
    battery_min_v: float
    battery_max_v: float
    max_pv_input_kw: float
    charge_current_a: float
    discharge_current_a: float
    efficiency_pct: float
    voltage_class: str
    sources: tuple[str, ...]
    battery_ports: int = 1
    max_parallel_units: int = 1
    estimated: bool = False
    supports_grid_export: bool = True
    phase_count: int = 1
    supports_no_battery: bool = True


@dataclass(frozen=True)
class BatterySpec:
    model: str
    module_kwh: float
    nominal_v: float
    min_v: float
    max_v: float
    charge_current_a: float
    discharge_current_a: float
    pulse_current_a: float
    max_parallel: int
    source: str
    min_series: int = 1
    max_series: int = 1
    max_dod_pct: float = 80.0


# Operating/continuous ratings, not VA ratings or brief overload ratings.
INVERTER_CATALOG = (
    InverterSpec("Estimated 1 kW / 24 V planning assembly", 1, 2.2, 18.4, 34,
                 1.4, 50, 50, 91, "24 V", (VICTRON_INVERTER, VICTRON_MPPT), estimated=True, supports_grid_export=False, supports_no_battery=False),
    InverterSpec("Deye SUN-3K-SG04LP1-24-EU", 3, 6, 20, 30, 4.8, 140, 140, 96.5, "24 V", (DEYE_SMALL, DEYE_SMALL_MANUAL)),
    InverterSpec("Deye SUN-5K-SG05LP1-EU-SM2-P", 5, 10, 40, 60, 8, 120, 120, 96.5, "48 V", (DEYE_MID,)),
    InverterSpec("Deye SUN-6K-SG05LP1-EU-SM2-P", 6, 12, 40, 60, 9.6, 135, 135, 96.5, "48 V", (DEYE_MID,)),
    InverterSpec("Deye SUN-8K-SG05LP1-EU-SM2-P", 8, 16, 40, 60, 12.8, 190, 190, 96.5, "48 V", (DEYE_MID,)),
    InverterSpec("Deye SUN-10K-SG05LP1-EU-SM2-P", 10, 20, 40, 60, 16, 210, 210, 96.5, "48 V", (DEYE_MID,)),
    InverterSpec("Deye SUN-12K-SG01LP1-EU-AM3-P", 12, 24, 40, 60, 19.2, 220, 220, 96.5, "48 V", (DEYE_LARGE,)),
    InverterSpec("Deye SUN-16K-SG01LP1-EU-AM3-P", 16, 32, 40, 60, 25.6, 290, 290, 96.5, "48 V", (DEYE_LARGE,)),
    InverterSpec("Deye SUN-18K-SG01LP1-EU-AM3-P", 18, 36, 40, 60, 28.8, 380, 380, 96.5, "48 V", (DEYE_LARGE,)),
    InverterSpec("Deye SUN-20K-SG01HP3-EU-AM2", 20, 30, 160, 700, 26, 50, 50, 97, "High voltage", (DEYE_HV_MID,), phase_count=3),
    InverterSpec("Deye SUN-25K-SG01HP3-EU-AM2", 25, 37.5, 160, 700, 32.5, 50, 50, 97, "High voltage", (DEYE_HV_MID,), phase_count=3),
    InverterSpec("Deye SUN-30K-SG01HP3-EU-BM3", 30, 45, 160, 800, 39, 100, 100, 97, "High voltage", (DEYE_HV,), 2, phase_count=3),
    InverterSpec("Deye SUN-40K-SG01HP3-EU-BM4", 40, 60, 160, 800, 52, 100, 100, 97, "High voltage", (DEYE_HV,), 2, phase_count=3),
    InverterSpec("Deye SUN-50K-SG01HP3-EU-BM4", 50, 75, 160, 800, 65, 100, 100, 97, "High voltage", (DEYE_HV,), 2, 10, phase_count=3),
)

BATTERY_CATALOG = {
    "24 V": BatterySpec("Victron Lithium NG 25.6 V / 100 Ah + external BMS", 2.56,
                        25.6, 22.4, 28.4, 100, 100, 200, 50, VICTRON_BATTERY),
    "48 V": BatterySpec("Deye SE-G5.1", 5.12, 51.2, 44.8, 57.6, 50, 50, 100, 64, DEYE_LV_BATTERY),
    "High voltage": BatterySpec("Deye BOS-GM5.1 + HVB controller per string", 5.12,
                                51.2, 44.8, 57.6, 100, 100, 100, 2, DEYE_HV_BATTERY, 4, 12, 90),
}


@dataclass
class EquipmentDesign:
    pv_required_kw: float = 0.0
    pv_capacity_kw: float = 0.0
    required_inverter_kw: float = 0.0
    inverter_rated_kw: float = 0.0
    inverter_unit_kw: float = 0.0
    inverter_count: int = 0
    inverter_model: str = ""
    inverter_phase_count: int = 1
    inverter_surge_kw: float = 0.0
    inverter_efficiency_pct: float = 100.0
    supports_grid_export: bool = True
    max_pv_input_kw: float = 0.0
    max_pv_conversion_kw: float = 0.0
    max_pv_charging_kw: float = 0.0
    max_battery_charge_kw: float = 0.0
    max_battery_discharge_kw: float = 0.0
    battery_required_kwh: float = 0.0
    battery_total_kwh: float = 0.0
    battery_voltage: float = 0.0
    battery_voltage_class: str = "No battery"
    battery_model: str = "No battery"
    battery_module_kwh: float = 0.0
    battery_module_count: int = 0
    battery_series_modules: int = 0
    battery_parallel_strings: int = 0
    battery_charge_current_a: float = 0.0
    battery_discharge_current_a: float = 0.0
    battery_pulse_current_a: float = 0.0
    battery_voltage_min: float = 0.0
    battery_voltage_max: float = 0.0
    dc_ac_ratio: float = 0.0
    peak_load_kw: float = 0.0
    surge_load_kw: float = 0.0
    daytime_kwh: float = 0.0
    nighttime_kwh: float = 0.0
    effective_dod_pct: float = 80.0
    storage_enabled: bool = True
    estimated: bool = True
    feasible: bool = True
    error: str = ""
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    catalog_review_date: str = CATALOG_REVIEW_DATE

    def as_dict(self) -> dict:
        return asdict(self)


def _number(value, default=0.0) -> float:
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return value if math.isfinite(value) else default


def _ceil_units(value: float) -> int:
    return max(1, math.ceil(value - 1e-10))


def calibrated_peak_sun_hours(peak_sun_hours: float, weather_factors: dict,
                              weather_mix: dict, resource_is_all_sky: bool) -> float:
    """Calibrate scenarios to an imported all-sky annual resource, not twice derate it."""
    if not resource_is_all_sky:
        return peak_sun_hours
    from logic.quote_validation import validate_weather_mix
    if validate_weather_mix(weather_mix):
        raise ValueError("Annual weather mix must total 100% before all-sky calibration.")
    if set(weather_factors) != {"Sunny", "Cloudy", "Rainy"} or not all(
            isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100
            for v in weather_factors.values()):
        raise ValueError("Weather factors must be between 0 and 100%.")
    fraction = sum(float(weather_mix[name]) / 100 * weather_factors[name] / 100 for name in weather_mix)
    if fraction <= 0:
        raise ValueError("All-sky solar resource cannot be calibrated with zero weather output.")
    calibrated = peak_sun_hours / fraction
    if not 0 <= calibrated <= 24:
        raise ValueError("Weather assumptions imply more than 24 peak sun hours; adjust the mix or factors.")
    return calibrated


def select_equipment_design(
    monthly_kwh: float, hourly_pct: list[float], peak_sun_hours: float,
    system_efficiency_pct: float, battery_dod_pct: float = 80,
    battery_efficiency_pct: float = 90, storage_enabled: bool = True,
    peak_load_kw: float | None = None, surge_load_kw: float | None = None,
    load_headroom_pct: float = 25, target_dc_ac_ratio: float = 1.5,
    harvest_pct: list[float] | None = None,
    production_peak_sun_hours: float | None = None,
) -> EquipmentDesign:
    """Select the smallest compatible planning configuration; never clamp demand.

    PV loss assumption excludes the catalog's inverter conversion efficiency.
    Battery sizing includes round-trip and inverter losses. Currents are converted
    to power at the bank's lower operating voltage, preserving limits across SOC.
    """
    design = EquipmentDesign(storage_enabled=bool(storage_enabled))
    from logic.quote_validation import validate_hourly_profile
    error = validate_hourly_profile(hourly_pct)
    if error:
        design.feasible, design.error = False, error
        return design
    values = (monthly_kwh, peak_sun_hours, system_efficiency_pct, battery_dod_pct,
              battery_efficiency_pct, load_headroom_pct, target_dc_ac_ratio)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values) or monthly_kwh < 0:
        design.feasible, design.error = False, "Sizing inputs must be finite, non-negative numbers."
        return design
    if not (0 < peak_sun_hours <= 24 and 0 < system_efficiency_pct <= 100 and
            0 < battery_dod_pct <= 100 and 0 < battery_efficiency_pct <= 100 and
            0 <= load_headroom_pct <= 100 and 1 <= target_dc_ac_ratio <= 2):
        design.feasible, design.error = False, "Sizing assumptions are outside their valid ranges."
        return design
    for name, value in (("Peak demand", peak_load_kw), ("Surge demand", surge_load_kw)):
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            design.feasible, design.error = False, f"{name} must be a finite non-negative kW value."
            return design
    load = hourly_kwh_from_percentages(monthly_kwh, [float(v) for v in hourly_pct])
    day, night = sum(load[:12]), sum(load[12:])
    measured_peak = _number(peak_load_kw)
    peak = max(max(load, default=0.0), measured_peak)
    surge = max(peak, _number(surge_load_kw))
    shape = default_solar_harvest_pct() if harvest_pct is None else harvest_pct
    if (len(shape) != 12 or not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in shape)
            or not math.isfinite(sum(shape)) or sum(shape) <= 0):
        design.feasible, design.error = False, "Solar profile must contain 12 non-negative values with positive total."
        return design
    peak_psh = production_peak_sun_hours if production_peak_sun_hours is not None else peak_sun_hours
    if not isinstance(peak_psh, (int, float)) or not math.isfinite(peak_psh) or not 0 < peak_psh <= 24:
        design.feasible, design.error = False, "Peak solar resource is outside its valid range."
        return design
    store = bool(storage_enabled) and night > 1e-9
    if measured_peak <= 0:
        design.notes.append(f"Peak demand is estimated from hourly averages with {load_headroom_pct:g}% sizing headroom; appliance starting peaks are not measured.")
    if _number(surge_load_kw) <= 0:
        design.notes.append("No measured surge demand supplied; verify appliance starting loads before equipment purchase.")
    design.notes.append("Planning estimate: verify BMS protocol, PV strings, temperature derating, grid approval and installation with the selected equipment revision.")
    design.notes.append("Surge checks use brief inverter overload and battery pulse ratings. Their duration, BMS limits and available current must be confirmed; the hourly simulation models continuous power only.")

    candidates = [(spec, 1) for spec in INVERTER_CATALOG]
    candidates += [(INVERTER_CATALOG[-1], count) for count in range(2, INVERTER_CATALOG[-1].max_parallel_units + 1)]
    for spec, count in candidates:
        if not store and not spec.supports_no_battery:
            continue
        eff = spec.efficiency_pct / 100
        batt_eff = battery_efficiency_pct / 100
        daily_dc = (day + (night / batt_eff if store else night)) / eff
        pv_required = daily_dc / peak_sun_hours / (system_efficiency_pct / 100)
        if not math.isfinite(pv_required) or not math.isfinite(pv_required * 10):
            design.feasible, design.error = False, "Required capacity exceeds the supported numerical range."
            return design
        pv = math.ceil(pv_required * 10 - 1e-9) / 10 if pv_required > 0 else 0.0
        expected_dc_peak = pv * peak_psh * (system_efficiency_pct / 100) * max(shape) / sum(shape)
        required_ac = max(peak * (1 + load_headroom_pct / 100),
                          pv / target_dc_ac_ratio, expected_dc_peak * eff)
        if (spec.rated_kw * count + 1e-9 < required_ac or
                spec.surge_kw * count + 1e-9 < surge or pv > spec.max_pv_input_kw * count + 1e-9):
            continue
        battery = BATTERY_CATALOG[spec.voltage_class]
        dod = min(battery_dod_pct, battery.max_dod_pct)
        required_battery = night / (dod / 100) / batt_eff / eff if store else 0.0
        series, strings = 0, 0
        charge_a = discharge_a = charge_kw = discharge_kw = bank_min_v = bank_max_v = 0.0
        if store:
            if battery.max_series == 1:
                series = 1
                strings = max(_ceil_units(required_battery / battery.module_kwh),
                              _ceil_units(peak / eff * 1000 / (battery.min_v * battery.discharge_current_a)),
                              _ceil_units(surge / eff * 1000 / (battery.min_v * battery.pulse_current_a)))
                if strings > battery.max_parallel:
                    continue
            else:
                possibilities = []
                for nseries in range(battery.min_series, battery.max_series + 1):
                    if not (spec.battery_min_v <= nseries * battery.min_v and
                            nseries * battery.max_v <= spec.battery_max_v):
                        continue
                    port_a = spec.discharge_current_a / spec.battery_ports
                    nstrings = max(_ceil_units(required_battery / (nseries * battery.module_kwh)),
                                   _ceil_units(peak / eff * 1000 / (nseries * battery.min_v * port_a)),
                                   _ceil_units(surge / eff * 1000 / (nseries * battery.min_v * port_a)))
                    if nstrings <= spec.battery_ports * count:
                        possibilities.append((nseries * nstrings, nseries, nstrings))
                if not possibilities:
                    continue
                _, series, strings = min(possibilities)
            bank_min_v, bank_max_v = series * battery.min_v, series * battery.max_v
            if not (spec.battery_min_v <= bank_min_v and bank_max_v <= spec.battery_max_v):
                continue
            # HV uses separate 50 A ports/strings; currents do not add in series.
            inverter_charge_a = (min(strings, spec.battery_ports * count) * spec.charge_current_a / spec.battery_ports
                                 if battery.max_series > 1 else spec.charge_current_a * count)
            inverter_discharge_a = (min(strings, spec.battery_ports * count) * spec.discharge_current_a / spec.battery_ports
                                    if battery.max_series > 1 else spec.discharge_current_a * count)
            charge_a = min(inverter_charge_a, strings * battery.charge_current_a)
            discharge_a = min(inverter_discharge_a, strings * battery.discharge_current_a)
            charge_kw = charge_a * bank_min_v / 1000
            discharge_kw = min(spec.rated_kw * count, discharge_a * bank_min_v / 1000 * eff)
            if discharge_kw + 1e-9 < peak:
                continue
        result = EquipmentDesign(
            pv_required_kw=pv_required, pv_capacity_kw=pv, required_inverter_kw=required_ac,
            inverter_rated_kw=spec.rated_kw * count, inverter_unit_kw=spec.rated_kw,
            inverter_count=count, inverter_model=spec.model, inverter_efficiency_pct=spec.efficiency_pct,
            inverter_phase_count=spec.phase_count, inverter_surge_kw=spec.surge_kw * count,
            supports_grid_export=spec.supports_grid_export,
            max_pv_input_kw=spec.max_pv_input_kw * count,
            max_pv_conversion_kw=min(spec.max_pv_input_kw * count, charge_kw) if spec.estimated else spec.max_pv_input_kw * count,
            max_pv_charging_kw=min(spec.max_pv_input_kw * count, charge_kw),
            max_battery_charge_kw=charge_kw, max_battery_discharge_kw=discharge_kw,
            battery_required_kwh=required_battery, battery_total_kwh=series * strings * battery.module_kwh,
            battery_voltage=series * battery.nominal_v, battery_voltage_class=spec.voltage_class if store else "No battery",
            battery_model=battery.model if store else "No battery", battery_module_kwh=battery.module_kwh if store else 0,
            battery_module_count=series * strings, battery_series_modules=series,
            battery_parallel_strings=strings, battery_charge_current_a=charge_a,
            battery_discharge_current_a=discharge_a, battery_voltage_min=bank_min_v,
            battery_pulse_current_a=strings * battery.pulse_current_a,
            battery_voltage_max=bank_max_v, dc_ac_ratio=pv / (spec.rated_kw * count),
            peak_load_kw=peak, surge_load_kw=surge, daytime_kwh=day, nighttime_kwh=night,
            effective_dod_pct=dod, storage_enabled=store, sources=list(spec.sources), notes=list(design.notes),
        )
        if store:
            result.sources.append(battery.source)
        if dod < battery_dod_pct and store:
            result.notes.append(f"Depth of discharge limited to the selected battery's {dod:g}% planning rating.")
        if spec.estimated:
            result.notes.append("1 kW uses an estimated 24 V planning assembly. References are separate off-grid inverter/controller ratings; this is not a certified grid-tie hybrid product.")
            result.notes.append("The 1 kW assembly requires a battery, external BMS and an approved grid transfer arrangement. MPPT output current limits all PV delivery, including PV serving load.")
        if store and spec.voltage_class == "24 V":
            result.notes.append("Victron NG needs a separate compatible BMS; cross-brand control compatibility is not certified by this planning calculation.")
        if store and spec.voltage_class == "High voltage":
            result.notes.append("HV voltage envelope is conservatively prorated from the BOS-G 12-module reference (538-691 V); verify the installed string's BMS settings.")
        if spec.phase_count == 3:
            result.notes.append("Selected HP3 inverter requires three-phase electrical service. Site phase availability and phase load balance have not been entered or certified.")
        if count > 1:
            result.notes.append(f"{count} identical inverters in parallel; manufacturer commissioning and per-port string allocation required.")
        return result
    design.feasible = False
    design.error = "Demand exceeds a compatible catalog configuration; installer design is required. No undersized system has been substituted."
    design.daytime_kwh, design.nighttime_kwh = day, night
    design.peak_load_kw, design.surge_load_kw = peak, surge
    return design


def refresh_equipment_design(state) -> EquipmentDesign:
    """Single authoritative design used by every screen and exported proposal."""
    project = state.project
    for attr in ("peak_load_kw", "surge_load_kw", "site_latitude", "site_longitude",
                 "site_tilt_deg", "site_azimuth_deg", "site_shading_pct", "resource_source"):
        if hasattr(project, attr):
            setattr(state, attr, getattr(project, attr))
    profile = state.hourly_pct or default_hourly_percentages(project.daytime_ratio_pct)
    try:
        peak_psh = calibrated_peak_sun_hours(
            state.peak_sun_hours, state.weather_factors,
            getattr(state, "weather_mix", {"Sunny": 60, "Cloudy": 25, "Rainy": 15}),
            getattr(state, "resource_is_all_sky", False),
        )
    except (ValueError, TypeError, OverflowError) as exc:
        peak_psh = 0.0
        resource_error = str(exc)
    else:
        resource_error = ""
    design = select_equipment_design(
        project.monthly_kwh, profile, state.peak_sun_hours,
        state.efficiency_pct, state.battery_dod_pct,
        state.battery_efficiency_pct,
        bool(getattr(project, "storage_enabled", getattr(state, "storage_enabled", True))),
        getattr(project, "peak_load_kw", None) or getattr(state, "peak_load_kw", None),
        getattr(project, "surge_load_kw", None) or getattr(state, "surge_load_kw", None),
        harvest_pct=getattr(state, "harvest_pct", None),
        production_peak_sun_hours=peak_psh,
    )
    if resource_error:
        design.feasible, design.error = False, resource_error
    state.design = design
    state.storage_enabled = bool(getattr(project, "storage_enabled", getattr(state, "storage_enabled", True)))
    state.solar_total_kw = design.pv_capacity_kw
    state.battery_total_kwh = design.battery_total_kwh
    state.battery_voltage = design.battery_voltage
    state.battery_usable_kwh = design.battery_total_kwh * design.effective_dod_pct / 100
    state.inverter_rated_power_kw = design.inverter_rated_kw
    state.inverter_max_pv_input_kw = design.max_pv_input_kw
    state.inverter_max_pv_charging_kw = design.max_pv_charging_kw
    state.inverter_max_battery_charge_kw = design.max_battery_charge_kw
    state.inverter_max_battery_discharge_kw = design.max_battery_discharge_kw
    state.inverter_efficiency_pct = design.inverter_efficiency_pct
    return design
