"""Simulation screen (ported from the desktop app's ui/simulation.py).

Redesigned around a single active-scenario view: pick Sunny/Cloudy/Rainy from a
dropdown and the whole tab re-themes (translucent tint + weather icon/rain
background, plus matching field/stat backgrounds) to match, showing one
6AM-to-6AM chart -- Consumption (red), Solar/Harvest (yellow), Grid (blue, net
buy/sell), and Battery (green, dashed) plotted as actual kWh held in the
battery each hour (SOC% * total capacity), all on one kW-scaled axis -- and a
summary row below it. The editable harvest table and the 3-scenario comparison
table from the desktop version are dropped in favor of this simpler
single-scenario view. Solar harvest is scaled by the client's country
latitude -- see logic/geo_data.py. All simulation math is otherwise unchanged,
from the ported logic/simulation.py.
"""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.textfield import MDTextField

from logic.calculations import HOUR_LABELS, hourly_kwh_from_percentages
from logic.chart_series import DOD_FLOOR_COLOR, SERIES_COLORS, series_for_result
from logic.geo_data import latitude_for_country, solar_latitude_factor
from logic.simulation import (
    DEFAULT_WEATHER_FACTORS,
    default_solar_harvest_pct,
    hourly_solar_kwh,
    run_steady_state_simulation,
)
from ui_style import (
    HEADER_BG, TEXT_DARK, WHITE, framed_label, picker_field, primary_button,
    screen_header, section_label, stat_title_label, tonal_button, with_bg,
)
from widgets.legend_swatch import LegendSwatch
from widgets.line_chart import LineChart
from widgets.weather_bg import WeatherBackground, rect_tint

SCENARIOS = ["Sunny", "Cloudy", "Rainy"]


class SimulationScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "simulation"
        self.hourly_consumption_kwh = [0.0] * 24
        self.pv_capacity_kw = 0.0
        self.peak_sun_hours = 4.5
        # Fixed at 100% -- see on_pre_enter. The Solar screen's user-editable
        # efficiency still applies to sizing (how big a system to recommend);
        # simulated/projected production always assumes full nameplate output.
        self.system_efficiency_pct = 100.0
        self.battery_total_kwh = 0.0
        self.battery_dod_pct = 80.0
        self.battery_efficiency_pct = 90.0
        self.max_battery_charge_kw = 5.0
        self.max_battery_discharge_kw = 5.0
        self.harvest_pct = default_solar_harvest_pct()
        self.active_scenario = "Sunny"
        self.latitude_factor = 1.0
        self._scenario_menu: MDDropdownMenu | None = None
        self._weather_fields: dict[str, MDTextField] = {}
        self._retintable_fields: list[MDTextField] = []
        self._retintable_labels: list[MDLabel] = []
        self._table_expanded = False
        self._last_hours: list = []
        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header("Simulation", step=6, on_back=self._go_back))

        self.big_bg = WeatherBackground(self.active_scenario)
        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(14), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        # This screen re-themes to the active weather scenario (see WeatherBackground /
        # rect_tint), so its fields/stats keep their own translucent tinted style rather
        # than the flat M3 section_card used elsewhere -- a tonal card here would fight
        # that theming instead of matching it.
        form.add_widget(section_label("weather-partly-cloudy", "Weather Scenarios & Grid Export"))
        weather_row = MDBoxLayout(spacing=dp(6), size_hint_y=None, height=dp(48))
        for name in SCENARIOS:
            field = self._tinted_field(hint_text=f"{name} %", input_filter="float",
                                        text=f"{DEFAULT_WEATHER_FACTORS[name]:.1f}")
            field.bind(text=lambda *_a: self._recalculate())
            self._weather_fields[name] = field
            weather_row.add_widget(field)
        form.add_widget(weather_row)

        self.scenario_field = picker_field("weather-sunny", "Active Scenario", "Sunny", self._open_scenario_menu)
        form.add_widget(self.scenario_field)

        export_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.export_checkbox = MDCheckbox(active=True, size_hint=(None, None), size=(dp(32), dp(32)))
        self.export_checkbox.bind(active=lambda *_a: self._recalculate())
        export_row.add_widget(self.export_checkbox)
        export_row.add_widget(MDLabel(
            text="Enable Net Metering / Grid Export", theme_text_color="Custom", text_color=TEXT_DARK,
        ))
        form.add_widget(export_row)

        form.add_widget(section_label("chart-line", "Simulation (6 AM - 6 AM)"))
        form.add_widget(self._build_legend())

        self.chart = LineChart(size_hint_y=None, height=dp(280))
        form.add_widget(self.chart)

        form.add_widget(section_label("gauge", "Summary"))
        summary = MDBoxLayout(spacing=dp(4), padding=(dp(4), dp(2)), size_hint_y=None, height=dp(56))
        self.harvest_label = self._make_stat(summary, "Harvest")
        self.consumption_label = self._make_stat(summary, "Load")
        self.grid_label = self._make_stat(summary, "Grid")
        self.battery_label = self._make_stat(summary, "Battery")
        form.add_widget(summary)

        self.table_toggle_btn = tonal_button("Show Hourly Data Table", on_release=self._toggle_table)
        form.add_widget(self.table_toggle_btn)
        self.table_container = MDBoxLayout(orientation="vertical", size_hint_y=None, height=0)
        form.add_widget(self.table_container)

        form.add_widget(primary_button("Next: Savings & ROI", on_release=self._go_next))

        scroll.add_widget(form)
        self.big_bg.add_widget(scroll)
        root.add_widget(self.big_bg)
        self.add_widget(root)

    def _tinted_field(self, **kwargs) -> MDTextField:
        kwargs.setdefault("mode", "fill")
        kwargs.setdefault("fill_color_normal", rect_tint(self.active_scenario))
        kwargs.setdefault("fill_color_focus", WHITE)
        field = MDTextField(**kwargs)
        self._retintable_fields.append(field)
        return field

    def _make_stat(self, row: MDBoxLayout, title: str) -> MDLabel:
        box = MDBoxLayout(orientation="vertical")
        box.add_widget(stat_title_label(title))
        value_label = with_bg(
            MDLabel(text="--", bold=True, halign="center", theme_text_color="Custom", text_color=TEXT_DARK),
            bg=rect_tint(self.active_scenario),
        )
        box.add_widget(value_label)
        row.add_widget(box)
        self._retintable_labels.append(value_label)
        return value_label

    def _build_legend(self) -> GridLayout:
        # 2 columns instead of one long row -- a single row of 4 labelled swatches
        # doesn't fit a phone's width and the last entry gets cut off.
        grid = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(52))
        for label, color in SERIES_COLORS.items():
            entry = MDBoxLayout(spacing=dp(4))
            entry.add_widget(LegendSwatch(color, dashed=(label == "Battery")))
            entry.add_widget(MDLabel(text=label, font_style="Caption",
                                      theme_text_color="Custom", text_color=TEXT_DARK))
            grid.add_widget(entry)
        return grid

    def _open_scenario_menu(self) -> None:
        items = [{"text": s, "on_release": lambda s=s: self._select_scenario(s)} for s in SCENARIOS]
        self._scenario_menu = MDDropdownMenu(caller=self.scenario_field, items=items, width_mult=3)
        self._scenario_menu.open()

    def _select_scenario(self, scenario: str) -> None:
        self.active_scenario = scenario
        self.scenario_field.set_value(scenario)
        if self._scenario_menu:
            self._scenario_menu.dismiss()
        self._retheme()
        self._recalculate()

    def _retheme(self) -> None:
        tint = rect_tint(self.active_scenario)
        self.big_bg.set_scenario(self.active_scenario)
        for field in self._retintable_fields:
            field.fill_color_normal = tint
        for label in self._retintable_labels:
            label.bg_color.rgba = tint

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        state = app.state
        self.hourly_consumption_kwh = hourly_kwh_from_percentages(
            state.project.monthly_kwh, state.hourly_pct or [0.0] * 24,
        )
        self.pv_capacity_kw = state.solar_total_kw
        self.peak_sun_hours = state.peak_sun_hours
        # Deliberately NOT state.efficiency_pct: the user's chosen efficiency still
        # drives sizing (Solar screen's required kW / recommended array size), but
        # simulated production, weather scenarios, and ROI all assume 100% -- the
        # system is sized conservatively (with the loss derate) but shown producing
        # at full nameplate output.
        self.system_efficiency_pct = 100.0
        self.battery_total_kwh = state.battery_total_kwh
        self.battery_dod_pct = state.battery_dod_pct
        self.battery_efficiency_pct = state.battery_efficiency_pct
        self.max_battery_charge_kw = state.inverter_max_battery_charge_kw
        self.max_battery_discharge_kw = state.inverter_max_battery_discharge_kw

        latitude = latitude_for_country(state.project.country)
        self.latitude_factor = solar_latitude_factor(latitude) if latitude is not None else 1.0

        self.big_bg.start()
        self._recalculate()

    def on_leave(self, *_args) -> None:
        self.big_bg.stop()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        try:
            return float(field.text)
        except ValueError:
            return default

    def _run_for_factor(self, weather_factor_pct: float):
        solar = hourly_solar_kwh(
            self.pv_capacity_kw, self.peak_sun_hours, self.system_efficiency_pct,
            weather_factor_pct * self.latitude_factor, self.harvest_pct,
        )
        return run_steady_state_simulation(
            hourly_consumption_kwh=self.hourly_consumption_kwh,
            hourly_solar_kwh_values=solar,
            hour_labels=HOUR_LABELS,
            battery_total_kwh=self.battery_total_kwh,
            battery_dod_pct=self.battery_dod_pct,
            battery_efficiency_pct=self.battery_efficiency_pct,
            max_battery_charge_kw=self.max_battery_charge_kw,
            max_battery_discharge_kw=self.max_battery_discharge_kw,
            grid_export_enabled=self.export_checkbox.active,
        )

    def _series_for_result(self, result) -> tuple[list[tuple], list[str], list]:
        return series_for_result(result, self.battery_total_kwh)

    def _toggle_table(self) -> None:
        self._table_expanded = not self._table_expanded
        self.table_toggle_btn.text = "Hide Hourly Data Table" if self._table_expanded else "Show Hourly Data Table"
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table_container.clear_widgets()
        if not self._table_expanded or not self._last_hours:
            self.table_container.height = 0
            return

        row_h = dp(30)
        headers = ["Hour", "Consum.", "Solar", "Grid", "Battery kWh"]
        grid = GridLayout(cols=len(headers), size_hint_y=None, spacing=dp(1), padding=dp(1),
                           row_default_height=row_h, row_force_default=True)
        for h in headers:
            grid.add_widget(framed_label(h, row_h, bold=True, bg=HEADER_BG))
        for hour in self._last_hours:
            battery_kwh = hour.soc_end_pct / 100 * self.battery_total_kwh
            grid.add_widget(framed_label(hour.hour_label, row_h))
            grid.add_widget(framed_label(f"{hour.consumption_kwh:.2f}", row_h))
            grid.add_widget(framed_label(f"{hour.solar_kwh:.2f}", row_h))
            grid.add_widget(framed_label(f"{hour.grid_export_kwh - hour.grid_purchase_kwh:+.2f}", row_h))
            grid.add_widget(framed_label(f"{battery_kwh:.2f}", row_h))

        rows = len(self._last_hours) + 1
        grid.height = rows * row_h + (rows - 1) * dp(1) + dp(2)
        self.table_container.add_widget(grid)
        self.table_container.height = grid.height

    def _recalculate(self) -> None:
        factor = self._float(self._weather_fields[self.active_scenario], DEFAULT_WEATHER_FACTORS[self.active_scenario])
        result = self._run_for_factor(factor)

        net_grid = result.total_grid_export_kwh - result.total_grid_purchase_kwh
        grid_word = "Sell" if net_grid >= 0 else "Buy"
        end_soc_pct = result.hours[-1].soc_end_pct if result.hours else 0.0
        end_battery_kwh = end_soc_pct / 100 * self.battery_total_kwh

        self.harvest_label.text = f"{result.total_solar_kwh:.2f} kWh"
        self.consumption_label.text = f"{result.total_consumption_kwh:.2f} kWh"
        self.grid_label.text = f"{net_grid:+.2f} kWh ({grid_word})"
        self.battery_label.text = f"{end_battery_kwh:.2f} kWh"

        series, x_labels, hours = self._series_for_result(result)
        dod_floor_kwh = self.battery_total_kwh * (1 - self.battery_dod_pct / 100)
        hline = {"y": dod_floor_kwh, "label": "DOD Floor", "color": DOD_FLOOR_COLOR}
        self.chart.set_data(series, x_labels, hline=hline)
        self._last_hours = hours
        self._refresh_table()

        app = MDApp.get_running_app()
        app.state.weather_factors = {n: self._float(f, DEFAULT_WEATHER_FACTORS[n])
                                      for n, f in self._weather_fields.items()}
        app.state.active_scenario = self.active_scenario
        app.state.export_enabled = self.export_checkbox.active
        app.state.harvest_pct = list(self.harvest_pct)
        # All 3 scenarios (not just the active one) so Savings & ROI can blend them by weather mix.
        app.state.scenario_results = {
            name: self._run_for_factor(self._float(self._weather_fields[name], DEFAULT_WEATHER_FACTORS[name]))
            for name in SCENARIOS
        }

    def get_report_data(self) -> dict:
        app = MDApp.get_running_app()
        return {
            "weather_factors": dict(app.state.weather_factors),
            "scenario_results": dict(app.state.scenario_results),
            "export_enabled": app.state.export_enabled,
            "harvest_pct": list(self.harvest_pct),
        }

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "system_design"

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "roi"
