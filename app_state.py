from logic.models import Project
from logic.simulation import DEFAULT_WEATHER_FACTORS, default_solar_harvest_pct

DEFAULT_ELECTRICITY_RATE = 14.50


class AppState:
    def __init__(self) -> None:
        self.project = Project(daytime_ratio_pct=70, electricity_rate=DEFAULT_ELECTRICITY_RATE)
        self.hourly_pct: list[float] = []
        self.peak_hourly_kwh: float = 0.0

        # Populated by SolarScreen; read by later screens (Battery, Inverter, Report, etc).
        # solar_total_kw is auto-picked from the same tier catalog as the inverter (see
        # logic.calculations.INVERTER_KW_TIERS) -- no separate panel wattage/count.
        self.peak_sun_hours: float = 4.5
        self.efficiency_pct: float = 80.0
        self.solar_total_kw: float = 0.0

        # Populated by BatteryScreen; read by later screens (Inverter, Report, etc).
        # battery_total_kwh is auto-picked from logic.calculations.BATTERY_CAPACITY_TIERS_KWH.
        self.battery_dod_pct: float = 80.0
        self.battery_efficiency_pct: float = 90.0
        self.battery_voltage: float = 48.0
        self.battery_total_kwh: float = 0.0
        self.battery_usable_kwh: float = 0.0

        # Populated by SystemDesignScreen; read by later screens (Simulation, Report, etc).
        self.inverter_rated_power_kw: float = 0.0
        self.inverter_max_pv_input_kw: float = 8.0
        self.inverter_max_pv_charging_kw: float = 6.0
        self.inverter_max_battery_charge_kw: float = 5.0
        self.inverter_max_battery_discharge_kw: float = 5.0
        self.inverter_efficiency_pct: float = 97.0

        # Populated by SimulationScreen; read by later screens (Savings & ROI, Report, etc).
        self.weather_factors: dict[str, float] = dict(DEFAULT_WEATHER_FACTORS)
        self.active_scenario: str = "Sunny"
        self.export_enabled: bool = True
        self.harvest_pct: list[float] = default_solar_harvest_pct()
        self.scenario_results: dict = {}  # {scenario_name: SimulationResult}, all 3 scenarios
