"""Savings & ROI screen (ported from the desktop app's ui/roi.py).

Two-column desktop layout (assumptions/weather-mix/graph left, big projection
table right) becomes a single scrollable column. The matplotlib cumulative
cash-flow chart is replaced by the same hand-drawn LineChart used on the
Simulation screen: a single line with marker dots, a green/red area fill above
and below zero, and a dashed vertical line at the payback year (where the
curve crosses zero) with its own legend entry. The 25-year financial table is
collapsible, same pattern as Simulation's hourly data table. All financial
math is unchanged, from the ported logic/financial.py.
"""

from kivy.metrics import dp
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from logic.chart_series import CASH_FLOW_COLOR, PAYBACK_COLOR, roi_chart_series
from logic.financial import (
    annual_electricity_cost_without_solar,
    annual_grid_cost_with_solar,
    blended_annual_kwh,
    build_projection_table,
    calculate_payback_years,
    net_benefit,
    roi_percent,
    total_electricity_savings,
)
from ui_style import (
    ACCENT, BAD_RED, HEADER_BG, OK_GREEN, TEXT_DARK, about_button, framed_label, go_home, header_actions, icon_button, m3_field, picker_field,
    keep_focused_field_visible, nav_row, save_button, save_current_project, screen_header, section_card, section_label, stat_title_label, tonal_button, with_bg,
)
from widgets.legend_swatch import LegendSwatch
from widgets.line_chart import LineChart

DEFAULT_WEATHER_MIX = {"Sunny": 60.0, "Cloudy": 25.0, "Rainy": 15.0}
DEFAULT_INFLATION_PCT = 3.0
DEFAULT_MAINTENANCE_PCT = 1.0
DEFAULT_MAINTENANCE_FIXED = 10_000.0
DEFAULT_EXPORT_RATE = 6.0
DEFAULT_SIMULATION_YEARS = 25
MAINTENANCE_METHODS = ["Percentage of System Cost", "Fixed Annual Amount"]


class RoiScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "roi"
        self.monthly_kwh = 0.0
        self.electricity_rate = 14.50
        self.scenario_results: dict = {}
        self.export_enabled = True
        self.maintenance_method = "percentage"
        self._table_expanded = False
        self._last_rows: list = []
        self._dialog: MDDialog | None = None
        self._method_menu: MDDropdownMenu | None = None
        self._mix_fields: dict[str, MDTextField] = {}
        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Savings & ROI", step=7, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about), icon_button("home-outline", on_release=go_home, color=ACCENT), save_button(on_release=save_current_project)),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        summary_card = section_card("gauge", "Savings & ROI Summary")
        summary1 = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(52))
        self.monthly_savings_label = self._make_stat(summary1, "Monthly Savings")
        self.annual_savings_label = self._make_stat(summary1, "Annual Savings")
        self.payback_label = self._make_stat(summary1, "Payback")
        summary_card.add_widget(summary1)
        summary2 = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(52))
        self.total_savings_label = self._make_stat(summary2, "N-Year Savings")
        self.net_benefit_label = self._make_stat(summary2, "Net Benefit")
        self.roi_pct_label = self._make_stat(summary2, "ROI %")
        summary_card.add_widget(summary2)
        summary_card.add_widget(tonal_button("SHOW CALCULATION", on_release=self._show_calculation))
        form.add_widget(summary_card)

        assumptions_card = section_card("cash-multiple", "Financial Assumptions")
        row1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.inflation_field = m3_field("Price Inflation %", icon="percent", input_filter="float",
                                         text=f"{DEFAULT_INFLATION_PCT:.1f}")
        self.export_rate_field = m3_field("Export Rate (PHP/kWh)", icon="transmission-tower-export",
                                           input_filter="float", text=f"{DEFAULT_EXPORT_RATE:.2f}")
        for f in (self.inflation_field, self.export_rate_field):
            f.bind(text=lambda *_a: self._recalculate())
            row1.add_widget(f)
        assumptions_card.add_widget(row1)

        self.maintenance_method_field = picker_field(
            "cog-outline", "Maintenance Method", MAINTENANCE_METHODS[0], self._open_method_menu,
        )
        assumptions_card.add_widget(self.maintenance_method_field)

        row2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.maintenance_pct_field = m3_field("Maintenance %", icon="percent", input_filter="float",
                                               text=f"{DEFAULT_MAINTENANCE_PCT:.2f}")
        self.maintenance_fixed_field = m3_field("Maintenance Fixed (PHP)", icon="cash", input_filter="float",
                                                  text=f"{DEFAULT_MAINTENANCE_FIXED:.2f}")
        for f in (self.maintenance_pct_field, self.maintenance_fixed_field):
            f.bind(text=lambda *_a: self._recalculate())
            row2.add_widget(f)
        assumptions_card.add_widget(row2)

        row3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.maintenance_inflation_field = m3_field("Maintenance Inflation %", icon="percent",
                                                      input_filter="float", text="0.0")
        self.years_field = m3_field("Simulation Years", icon="calendar-range", input_filter="int",
                                     text=str(DEFAULT_SIMULATION_YEARS))
        for f in (self.maintenance_inflation_field, self.years_field):
            f.bind(text=lambda *_a: self._recalculate())
            row3.add_widget(f)
        assumptions_card.add_widget(row3)

        self.system_cost_field = m3_field("Total Installed Solar System Cost (PHP)", icon="wallet-outline",
                                           input_filter="float", text="0")
        self.system_cost_field.bind(text=lambda *_a: self._recalculate())
        assumptions_card.add_widget(self.system_cost_field)
        form.add_widget(assumptions_card)

        mix_card = section_card("weather-partly-cloudy", "Annual Weather Mix")
        mix_card.add_widget(MDLabel(
            text="Share of the year in each weather scenario (from Simulation).",
            font_style="Caption", theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None, height=dp(20),
        ))
        mix_row = MDBoxLayout(spacing=dp(6), size_hint_y=None, height=dp(52))
        for name in ("Sunny", "Cloudy", "Rainy"):
            field = m3_field(f"{name} %", input_filter="float", text=f"{DEFAULT_WEATHER_MIX[name]:.1f}")
            field.bind(text=lambda *_a: self._recalculate())
            self._mix_fields[name] = field
            mix_row.add_widget(field)
        mix_card.add_widget(mix_row)
        self.mix_total_label = MDLabel(
            text="Total: 100.0% (must equal 100%)", size_hint_y=None, height=dp(20),
            theme_text_color="Custom", text_color=TEXT_DARK,
        )
        mix_card.add_widget(self.mix_total_label)
        form.add_widget(mix_card)

        form.add_widget(section_label("chart-line", "Cumulative Cash Flow vs Years"))
        form.add_widget(self._build_legend())
        self.chart = LineChart(size_hint_y=None, height=dp(220))
        form.add_widget(self.chart)

        self.table_toggle_btn = tonal_button("Show Financial Table", on_release=self._toggle_table)
        form.add_widget(self.table_toggle_btn)
        self.table_container = MDBoxLayout(orientation="vertical", size_hint_y=None, height=0)
        form.add_widget(self.table_container)

        form.add_widget(nav_row(self._go_back, "Next: Report", self._go_next))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _make_stat(self, row: MDBoxLayout, title: str) -> MDLabel:
        box = MDBoxLayout(orientation="vertical")
        box.add_widget(stat_title_label(title))
        value_label = with_bg(MDLabel(text="--", bold=True, halign="center",
                                       theme_text_color="Custom", text_color=ACCENT))
        box.add_widget(value_label)
        row.add_widget(box)
        return value_label

    def _build_legend(self) -> MDBoxLayout:
        row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(24))
        for label, color, dashed in [
            ("Cumulative Cash Flow", CASH_FLOW_COLOR, False),
            ("Payback", PAYBACK_COLOR, True),
        ]:
            entry = MDBoxLayout(spacing=dp(4), size_hint_x=None, width=dp(150))
            entry.add_widget(LegendSwatch(color, dashed=dashed))
            entry.add_widget(MDLabel(text=label, font_style="Caption",
                                      theme_text_color="Custom", text_color=TEXT_DARK))
            row.add_widget(entry)
        return row

    def _open_method_menu(self) -> None:
        items = [{"text": m, "on_release": lambda m=m: self._select_method(m)} for m in MAINTENANCE_METHODS]
        self._method_menu = MDDropdownMenu(caller=self.maintenance_method_field, items=items, width_mult=4)
        self._method_menu.open()

    def _select_method(self, method_label: str) -> None:
        self.maintenance_method = "percentage" if method_label == MAINTENANCE_METHODS[0] else "fixed"
        self.maintenance_method_field.set_value(method_label)
        if self._method_menu:
            self._method_menu.dismiss()
        self._recalculate()

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        state = app.state
        self.monthly_kwh = state.project.monthly_kwh
        self.electricity_rate = state.project.electricity_rate
        self.scenario_results = state.scenario_results
        self.export_enabled = state.export_enabled
        self._recalculate()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        try:
            return float(field.text)
        except ValueError:
            return default

    def _int(self, field: MDTextField, default: int = 1) -> int:
        try:
            return max(1, int(field.text))
        except ValueError:
            return default

    def _weather_mix_pct(self) -> dict:
        return {name: self._float(f, DEFAULT_WEATHER_MIX[name]) for name, f in self._mix_fields.items()}

    def _annual_figures(self) -> tuple[float, float]:
        weather_mix = self._weather_mix_pct()
        annual_purchase = blended_annual_kwh(self.scenario_results, weather_mix, "total_grid_purchase_kwh")
        annual_export = blended_annual_kwh(self.scenario_results, weather_mix, "total_grid_export_kwh")
        return annual_purchase, annual_export

    def _system_cost(self) -> float:
        return self._float(self.system_cost_field, 0.0)

    def _build_rows(self, annual_purchase: float, annual_export: float) -> list:
        return build_projection_table(
            system_cost=self._system_cost(),
            base_rate=self.electricity_rate,
            inflation_pct=self._float(self.inflation_field, DEFAULT_INFLATION_PCT),
            annual_kwh_without_solar=self.monthly_kwh * 12,
            annual_grid_purchase_kwh=annual_purchase,
            annual_grid_export_kwh=annual_export,
            export_rate=self._float(self.export_rate_field, DEFAULT_EXPORT_RATE),
            export_enabled=self.export_enabled,
            maintenance_method=self.maintenance_method,
            maintenance_pct=self._float(self.maintenance_pct_field, DEFAULT_MAINTENANCE_PCT),
            maintenance_fixed=self._float(self.maintenance_fixed_field, DEFAULT_MAINTENANCE_FIXED),
            maintenance_inflation_pct=self._float(self.maintenance_inflation_field, 0.0),
            years=self._int(self.years_field, DEFAULT_SIMULATION_YEARS),
        )

    def _recalculate(self) -> None:
        total_mix = sum(self._weather_mix_pct().values())
        mix_ok = abs(total_mix - 100) < 0.05
        self.mix_total_label.text = f"Total: {total_mix:.1f}% (must equal 100%)"
        self.mix_total_label.theme_text_color = "Custom"
        self.mix_total_label.text_color = OK_GREEN if mix_ok else BAD_RED

        annual_purchase, annual_export = self._annual_figures()
        annual_without = annual_electricity_cost_without_solar(self.monthly_kwh, self.electricity_rate)
        annual_with = annual_grid_cost_with_solar(
            annual_purchase, self.electricity_rate, annual_export,
            self._float(self.export_rate_field, DEFAULT_EXPORT_RATE), self.export_enabled,
        )
        annual_savings_value = annual_without - annual_with
        self.monthly_savings_label.text = f"P{annual_savings_value / 12:,.0f}"
        self.annual_savings_label.text = f"P{annual_savings_value:,.0f}"

        rows = self._build_rows(annual_purchase, annual_export)
        system_cost = self._system_cost()

        payback = calculate_payback_years(rows, system_cost)
        self.payback_label.text = f"{payback:.1f} yrs" if payback is not None else "N/A"
        total_savings = total_electricity_savings(rows)
        nb = net_benefit(rows, system_cost)
        roi = roi_percent(nb, system_cost)
        self.total_savings_label.text = f"P{total_savings:,.0f}"
        self.net_benefit_label.text = f"P{nb:,.0f}"
        self.roi_pct_label.text = f"{roi:.1f}%"

        series, x_labels, vline = roi_chart_series(system_cost, rows, payback)
        self.chart.set_data(series, x_labels, vline=vline, fill_index=0)

        self._last_rows = rows
        self._refresh_table()

    def get_report_data(self) -> dict:
        annual_purchase, annual_export = self._annual_figures()
        annual_without = annual_electricity_cost_without_solar(self.monthly_kwh, self.electricity_rate)
        annual_with = annual_grid_cost_with_solar(
            annual_purchase, self.electricity_rate, annual_export,
            self._float(self.export_rate_field, DEFAULT_EXPORT_RATE), self.export_enabled,
        )
        annual_savings_value = annual_without - annual_with
        system_cost = self._system_cost()
        rows = self._build_rows(annual_purchase, annual_export)
        nb = net_benefit(rows, system_cost)
        return {
            "system_cost": system_cost,
            "monthly_savings": annual_savings_value / 12,
            "annual_savings": annual_savings_value,
            "payback_years": calculate_payback_years(rows, system_cost),
            "total_savings": total_electricity_savings(rows),
            "net_benefit": nb,
            "roi_pct": roi_percent(nb, system_cost),
            "weather_mix": self._weather_mix_pct(),
            "export_rate": self._float(self.export_rate_field, DEFAULT_EXPORT_RATE),
            "inflation_pct": self._float(self.inflation_field, DEFAULT_INFLATION_PCT),
            "projection_rows": rows,
        }

    def collect_state(self) -> dict:
        return {
            "inflation_pct": self._float(self.inflation_field, DEFAULT_INFLATION_PCT),
            "export_rate": self._float(self.export_rate_field, DEFAULT_EXPORT_RATE),
            "maintenance_method": self.maintenance_method,
            "maintenance_pct": self._float(self.maintenance_pct_field, DEFAULT_MAINTENANCE_PCT),
            "maintenance_fixed": self._float(self.maintenance_fixed_field, DEFAULT_MAINTENANCE_FIXED),
            "maintenance_inflation_pct": self._float(self.maintenance_inflation_field, 0.0),
            "years": self._int(self.years_field, DEFAULT_SIMULATION_YEARS),
            "system_cost": self._system_cost(),
            "weather_mix": self._weather_mix_pct(),
        }

    def apply_state(self, data: dict) -> None:
        self.inflation_field.text = f"{data.get('inflation_pct', DEFAULT_INFLATION_PCT):.1f}"
        self.export_rate_field.text = f"{data.get('export_rate', DEFAULT_EXPORT_RATE):.2f}"
        self.maintenance_method = data.get("maintenance_method", "percentage")
        label = MAINTENANCE_METHODS[0] if self.maintenance_method == "percentage" else MAINTENANCE_METHODS[1]
        self.maintenance_method_field.set_value(label)
        self.maintenance_pct_field.text = f"{data.get('maintenance_pct', DEFAULT_MAINTENANCE_PCT):.2f}"
        self.maintenance_fixed_field.text = f"{data.get('maintenance_fixed', DEFAULT_MAINTENANCE_FIXED):.2f}"
        self.maintenance_inflation_field.text = f"{data.get('maintenance_inflation_pct', 0.0):.2f}"
        self.years_field.text = str(data.get("years", DEFAULT_SIMULATION_YEARS))
        self.system_cost_field.text = f"{data.get('system_cost', 0.0):.2f}"
        weather_mix = data.get("weather_mix") or {}
        for name, field in self._mix_fields.items():
            field.text = f"{weather_mix.get(name, DEFAULT_WEATHER_MIX[name]):.1f}"
        self._recalculate()

    def _toggle_table(self) -> None:
        self._table_expanded = not self._table_expanded
        self.table_toggle_btn.text = "Hide Financial Table" if self._table_expanded else "Show Financial Table"
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table_container.clear_widgets()
        if not self._table_expanded or not self._last_rows:
            self.table_container.height = 0
            return

        row_h = dp(30)
        headers = ["Year", "Rate", "Cost w/o", "Cost w/", "Savings", "Maint.", "Net", "Cumul."]
        grid = GridLayout(cols=len(headers), size_hint_y=None, spacing=dp(1), padding=dp(1),
                           row_default_height=row_h, row_force_default=True)
        for h in headers:
            grid.add_widget(framed_label(h, row_h, bold=True, bg=HEADER_BG))
        for row in self._last_rows:
            grid.add_widget(framed_label(str(row.year), row_h))
            grid.add_widget(framed_label(f"{row.electricity_rate:.2f}", row_h))
            grid.add_widget(framed_label(f"{row.grid_cost_without_solar:,.0f}", row_h))
            grid.add_widget(framed_label(f"{row.grid_cost_with_solar:,.0f}", row_h))
            grid.add_widget(framed_label(f"{row.electricity_savings:,.0f}", row_h))
            grid.add_widget(framed_label(f"{row.maintenance:,.0f}", row_h))
            grid.add_widget(framed_label(f"{row.net_savings:,.0f}", row_h))
            grid.add_widget(framed_label(f"{row.cumulative_cash_flow:,.0f}", row_h))

        rows_count = len(self._last_rows) + 1
        grid.height = rows_count * row_h + (rows_count - 1) * dp(1) + dp(2)
        self.table_container.add_widget(grid)
        self.table_container.height = grid.height

    def _show_calculation(self) -> None:
        annual_purchase, annual_export = self._annual_figures()
        annual_without = annual_electricity_cost_without_solar(self.monthly_kwh, self.electricity_rate)
        annual_with = annual_grid_cost_with_solar(
            annual_purchase, self.electricity_rate, annual_export,
            self._float(self.export_rate_field, DEFAULT_EXPORT_RATE), self.export_enabled,
        )
        text = (
            "Annual Savings = (Annual Cost Without Solar) - (Annual Grid Cost With Solar)\n"
            "Annual Grid Cost With Solar = Grid Purchase x Rate"
            + (" - Grid Export x Export Rate" if self.export_enabled else "") + "\n\n"
            f"Annual Cost Without Solar = {self.monthly_kwh:.2f} kWh x 12 x P{self.electricity_rate:.2f} "
            f"= P{annual_without:,.2f}\n"
            f"Blended Annual Grid Purchase = {annual_purchase:,.2f} kWh\n"
            f"Blended Annual Grid Export = {annual_export:,.2f} kWh\n"
            f"Annual Grid Cost With Solar = P{annual_with:,.2f}\n\n"
            f"Annual Savings = P{annual_without:,.2f} - P{annual_with:,.2f} = P{annual_without - annual_with:,.2f}"
        )
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="Savings - Calculation", text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "simulation"

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "report"
