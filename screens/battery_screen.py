"""Automatic battery voltage, module count and compatible power limits.

The hourly demand profile determines nighttime storage, including battery and
inverter losses. Disabled storage or zero nighttime demand needs no battery.
"""

from kivy.metrics import dp, Metrics
from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from logic.calculations import battery_usable_capacity_kwh
from logic.equipment import refresh_equipment_design
from logic.quote_validation import finite_float_or, live_float_or
from ui_style import (
    ACCENT, TEXT_DARK, about_button, go_home, header_actions, icon_button, m3_field, nav_row, save_button, save_current_project, screen_header, section_card, tonal_button, with_bg,
)

DEFAULT_BATTERY_DOD_PCT = 80.0
DEFAULT_BATTERY_EFFICIENCY_PCT = 90.0


class BatteryScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "battery"
        self.monthly_kwh = 0.0
        self.daytime_pct = 70
        self._dialog: MDDialog | None = None
        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Battery Sizing", step=4, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about), icon_button("home-outline", on_release=go_home, color=ACCENT), save_button(on_release=save_current_project)),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        assumptions_card = section_card("battery-charging", "Battery Assumptions")
        assumptions_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.dod_field = m3_field(
            "Depth of Discharge %", icon="battery-outline", input_filter="float",
            text=f"{DEFAULT_BATTERY_DOD_PCT:.1f}",
        )
        self.efficiency_field = m3_field(
            "Round Trip Efficiency %", icon="percent", input_filter="float",
            text=f"{DEFAULT_BATTERY_EFFICIENCY_PCT:.1f}",
        )
        for f in (self.dod_field, self.efficiency_field):
            f.bind(text=lambda *_a: self._recalculate())
            assumptions_row.add_widget(f)
        assumptions_card.add_widget(assumptions_row)

        self.voltage_label = MDLabel(
            text="Voltage and battery modules selected automatically for the inverter.",
            theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None, height=dp(72),
        )
        self.voltage_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                                texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(8)))
        assumptions_card.add_widget(self.voltage_label)
        form.add_widget(assumptions_card)

        result_card = section_card("battery-high", "Recommended Battery Capacity")
        self.nighttime_context_label = with_bg(MDLabel(
            text="Nighttime Consumption: -- kWh", theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None, height=dp(24),
        ))
        self.nighttime_context_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                                          texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(4)))
        result_card.add_widget(self.nighttime_context_label)

        result_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.recommended_label = with_bg(MDLabel(
            text="-- kWh", bold=True, halign="center", valign="middle",
            theme_text_color="Custom", text_color=ACCENT, size_hint_y=None, height=dp(44),
        ))
        result_row.add_widget(self.recommended_label)
        calculation_button = tonal_button(
            "SHOW CALCULATION", on_release=self._show_calculation, size_hint_x=None, width=dp(170),
        )
        result_row.add_widget(calculation_button)
        self.recommended_label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        def fit_result(*_args):
            vertical = result_row.width / max(1, Metrics.fontscale) < dp(320)
            result_row.orientation = "vertical" if vertical else "horizontal"
            calculation_button.size_hint_x = 1 if vertical else None
            if not vertical:
                calculation_button.width = dp(170)
            heights = [widget.height for widget in result_row.children]
            result_row.height = sum(heights) + result_row.spacing if vertical else max(heights, default=dp(48))
        result_row.bind(width=fit_result)
        self.recommended_label.bind(height=fit_result)
        calculation_button.bind(height=fit_result)
        Clock.schedule_once(fit_result)
        result_card.add_widget(result_row)

        self.usable_capacity_label = with_bg(MDLabel(
            text="Usable Battery Capacity: -- kWh", bold=True, theme_text_color="Custom", text_color=ACCENT,
            size_hint_y=None, height=dp(28),
        ))
        self.usable_capacity_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                                        texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(4)))
        result_card.add_widget(self.usable_capacity_label)
        form.add_widget(result_card)

        form.add_widget(nav_row(self._go_back, "Next: System Design", self._go_next))

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        self.monthly_kwh = app.state.project.monthly_kwh
        self.daytime_pct = app.state.project.daytime_ratio_pct
        self._recalculate()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        return live_float_or(field.text, default)

    def _nighttime_kwh(self) -> float:
        return self._design().nighttime_kwh

    def _design(self):
        state = MDApp.get_running_app().state
        state.battery_dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        state.battery_efficiency_pct = self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT)
        return refresh_equipment_design(state)

    def _required_kwh(self) -> float:
        return self._design().battery_required_kwh

    def _recommended_kwh(self) -> float:
        return self._design().battery_total_kwh

    def _recalculate(self) -> None:
        design = self._design()
        night_kwh = design.nighttime_kwh
        self.nighttime_context_label.text = f"Nighttime Consumption: {night_kwh:.2f} kWh"

        recommended = design.battery_total_kwh
        self.recommended_label.text = f"{recommended:.2f} kWh" if design.feasible else "Design unavailable"

        dod_pct = design.effective_dod_pct
        usable_kwh = battery_usable_capacity_kwh(recommended, dod_pct)
        self.usable_capacity_label.text = f"Usable Battery Capacity: {usable_kwh:.2f} kWh"

        self.voltage_label.text = (
            f"Auto: {design.battery_voltage_class}, {design.battery_voltage:g} V nominal; "
            f"{design.battery_module_count} x {design.battery_module_kwh:g} kWh modules.\n"
            f"{design.battery_series_modules} in series x {design.battery_parallel_strings} strings. "
            f"Charge/discharge limits: {design.max_battery_charge_kw:.2f} / {design.max_battery_discharge_kw:.2f} kW."
            if design.storage_enabled else "No battery selected: storage disabled or no nighttime demand."
        ) if design.feasible else design.error

    def get_report_data(self) -> dict:
        design = self._design()
        dod_pct = design.effective_dod_pct
        recommended = design.battery_total_kwh
        return {
            "dod_pct": dod_pct,
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT),
            "required_kwh": self._required_kwh(),
            "voltage": design.battery_voltage,
            "total_kwh": recommended,
            "usable_kwh": battery_usable_capacity_kwh(recommended, dod_pct),
            "module_kwh": design.battery_module_kwh,
            "module_count": design.battery_module_count,
            "series_modules": design.battery_series_modules,
            "parallel_strings": design.battery_parallel_strings,
            "voltage_class": design.battery_voltage_class,
            "model": design.battery_model,
            "charge_current_a": design.battery_charge_current_a,
            "discharge_current_a": design.battery_discharge_current_a,
            "storage_enabled": design.storage_enabled,
            "equipment": design.as_dict(),
            "selection_error": design.error,
        }

    def collect_state(self) -> dict:
        design = self._design()
        return {
            "dod_pct": self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT),
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT),
            "voltage": design.battery_voltage,
            "storage_enabled": design.storage_enabled,
            "selection_error": design.error,
        }

    def apply_state(self, data: dict) -> None:
        self.dod_field.text = f"{finite_float_or(data.get('dod_pct'), DEFAULT_BATTERY_DOD_PCT):.6f}"
        self.efficiency_field.text = f"{finite_float_or(data.get('efficiency_pct'), DEFAULT_BATTERY_EFFICIENCY_PCT):.6f}"
        self._recalculate()

    def _show_calculation(self) -> None:
        night_kwh = self._nighttime_kwh()
        dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT)
        required_kwh = self._required_kwh()
        recommended = self._recommended_kwh()
        design = self._design()
        text = (
            "Required Battery = profile's nighttime load / allowed DOD / battery efficiency / inverter efficiency.\n\n"
            f"Night load: {night_kwh:.2f} kWh; requested DOD: {dod_pct:.0f}%; battery efficiency: {efficiency_pct:.0f}%.\n"
            f"= {required_kwh:.2f} kWh\n\n"
            f"Compatible modules selected for capacity, voltage and current: {recommended:.2f} kWh.\n"
            "Voltage is automatic: 24 V, 48 V or a compatible high-voltage series bank."
        ) if design.feasible else design.error
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="Recommended Battery Capacity - Calculation", text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "solar"

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        if not self._design().feasible:
            self._show_calculation()
            return
        app = MDApp.get_running_app()
        app.root.current = "system_design"
