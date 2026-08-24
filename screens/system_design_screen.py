"""System Design (Inverter) screen (ported from the desktop app's ui/system_design.py).

The inverter rating is now auto-picked (rounded up to the next available spec, from
logic.calculations.INVERTER_KW_TIERS) instead of a manually-typed value -- since
SolarScreen already sizes the array as max(peak load, required solar kW) rounded up
to this exact same catalog, the inverter's own recommendation is always that same
figure, so the two specs are guaranteed to match. The other assumption fields (max
PV input/charging, battery charge/discharge limits, inverter efficiency) stay
editable -- they're independent installer-tunable limits the engineering warnings
below check the auto-picked inverter against, not part of what needed automating.
All sizing math is unchanged, from the ported logic/calculations.py.
"""

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from logic.calculations import INVERTER_KW_TIERS, required_inverter_kw, round_up_to_standard_size
from ui_style import (
    ACCENT, TEXT_DARK, about_button, go_home, header_actions, icon_button, keep_focused_field_visible, m3_field, nav_row, save_button, save_current_project, screen_header, section_card, section_label,
    tonal_button, warning_row, with_bg,
)

DEFAULT_MAX_PV_INPUT = 8.0
DEFAULT_MAX_PV_CHARGING = 6.0
DEFAULT_MAX_BATTERY_CHARGE = 5.0
DEFAULT_MAX_BATTERY_DISCHARGE = 5.0
DEFAULT_INVERTER_EFFICIENCY_PCT = 97.0


class SystemDesignScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "system_design"
        self.peak_hourly_kwh = 0.0
        self.pv_capacity_kw = 0.0
        self.battery_total_kwh = 0.0
        self.battery_usable_kwh = 0.0
        self._dialog: MDDialog | None = None
        self._build_ui()
        self._recalculate_recommendation()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "System Design", step=5, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about), icon_button("home-outline", on_release=go_home, color=ACCENT), save_button(on_release=save_current_project)),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        result_card = section_card("flash-outline", "Recommended Inverter")
        result_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.recommended_label = with_bg(MDLabel(
            text="-- kW", bold=True, theme_text_color="Custom", text_color=ACCENT,
        ))
        result_row.add_widget(self.recommended_label)
        result_row.add_widget(tonal_button(
            "SHOW CALCULATION", on_release=self._show_calculation, size_hint_x=None, width=dp(170),
        ))
        result_card.add_widget(result_row)
        form.add_widget(result_card)

        assumptions_card = section_card("tune-variant", "Inverter Assumptions")
        row1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.max_pv_input_field = self._field("Max PV Input (kW)", f"{DEFAULT_MAX_PV_INPUT:.2f}", "solar-power")
        self.max_pv_charging_field = self._field(
            "Max PV Charging (kW)", f"{DEFAULT_MAX_PV_CHARGING:.2f}", "battery-sync-outline",
        )
        row1.add_widget(self.max_pv_input_field)
        row1.add_widget(self.max_pv_charging_field)
        assumptions_card.add_widget(row1)

        row2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.max_battery_charge_field = self._field(
            "Max Battery Charge (kW)", f"{DEFAULT_MAX_BATTERY_CHARGE:.2f}", "battery-charging",
        )
        self.max_battery_discharge_field = self._field(
            "Max Battery Discharge (kW)", f"{DEFAULT_MAX_BATTERY_DISCHARGE:.2f}", "battery-high",
        )
        row2.add_widget(self.max_battery_charge_field)
        row2.add_widget(self.max_battery_discharge_field)
        assumptions_card.add_widget(row2)

        self.inverter_efficiency_field = self._field(
            "Inverter Efficiency %", f"{DEFAULT_INVERTER_EFFICIENCY_PCT:.1f}", "percent",
        )
        assumptions_card.add_widget(self.inverter_efficiency_field)
        form.add_widget(assumptions_card)

        for f in (
            self.max_pv_input_field, self.max_pv_charging_field,
            self.max_battery_charge_field, self.max_battery_discharge_field,
        ):
            f.bind(text=lambda *_a: self._on_selection_changed())

        form.add_widget(section_label("alert-outline", "Engineering Warnings"))
        self.warnings_container = MDBoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None)
        self.warnings_container.bind(minimum_height=self.warnings_container.setter("height"))
        form.add_widget(self.warnings_container)

        summary_card = section_card("clipboard-text-outline", "Final Selected System")
        self.final_solar_label = self._summary_line(summary_card, "Solar")
        self.final_inverter_label = self._summary_line(summary_card, "Inverter")
        self.final_battery_label = self._summary_line(summary_card, "Battery")
        form.add_widget(summary_card)

        form.add_widget(nav_row(self._go_back, "Next: Simulation", self._go_next))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _field(self, hint: str, text: str, icon: str) -> MDTextField:
        return m3_field(hint, icon=icon, input_filter="float", text=text)

    def _summary_line(self, container: MDBoxLayout, title: str) -> MDLabel:
        row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(28))
        row.add_widget(MDLabel(text=title, theme_text_color="Custom", text_color=TEXT_DARK, size_hint_x=0.3))
        value_label = with_bg(MDLabel(text="--", bold=True, theme_text_color="Custom", text_color=ACCENT))
        row.add_widget(value_label)
        container.add_widget(row)
        return value_label

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        state = app.state
        self.peak_hourly_kwh = state.peak_hourly_kwh
        self.pv_capacity_kw = state.solar_total_kw
        self.battery_total_kwh = state.battery_total_kwh
        self.battery_usable_kwh = state.battery_usable_kwh
        self._recalculate_recommendation()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        try:
            return float(field.text)
        except ValueError:
            return default

    def _required_kw(self) -> float:
        return required_inverter_kw(self.peak_hourly_kwh, self.pv_capacity_kw)

    def _recommended_kw(self) -> float:
        return round_up_to_standard_size(self._required_kw(), INVERTER_KW_TIERS) or 0.0

    def _recalculate_recommendation(self) -> None:
        self.recommended_label.text = f"{self._recommended_kw():.2f} kW"
        self._update_warnings()
        self._update_final_summary()

    def _on_selection_changed(self) -> None:
        self._update_warnings()
        self._update_final_summary()

    def _warning_items(self) -> list[tuple[bool, str]]:
        rated_power = self._recommended_kw()
        required_kw = self._required_kw()

        items = []

        undersized = rated_power < required_kw
        items.append((
            not undersized,
            f"Inverter rated power ({rated_power:.2f} kW) "
            f"{'meets' if not undersized else 'is below'} the recommended capacity ({required_kw:.2f} kW).",
        ))

        max_pv_input = self._float(self.max_pv_input_field, DEFAULT_MAX_PV_INPUT)
        pv_exceeds = self.pv_capacity_kw > max_pv_input
        items.append((
            not pv_exceeds,
            f"PV capacity ({self.pv_capacity_kw:.2f} kW) "
            f"{'is within' if not pv_exceeds else 'exceeds'} the inverter's maximum PV input "
            f"({max_pv_input:.2f} kW).",
        ))

        load_exceeds = self.peak_hourly_kwh > rated_power
        items.append((
            not load_exceeds,
            f"Peak load ({self.peak_hourly_kwh:.2f} kW) "
            f"{'is within' if not load_exceeds else 'exceeds'} the inverter's rated output "
            f"({rated_power:.2f} kW).",
        ))

        return items

    def _update_warnings(self) -> None:
        self.warnings_container.clear_widgets()
        for ok, text in self._warning_items():
            self.warnings_container.add_widget(warning_row(ok, text))

    def _update_final_summary(self) -> None:
        app = MDApp.get_running_app()
        rated_power = self._recommended_kw()

        self.final_solar_label.text = f"{self.pv_capacity_kw:.2f} kWp"
        self.final_inverter_label.text = f"{rated_power:.2f} kW"
        self.final_battery_label.text = (
            f"{self.battery_total_kwh:.2f} kWh (usable {self.battery_usable_kwh:.2f} kWh)"
        )

        app.state.inverter_rated_power_kw = rated_power
        app.state.inverter_max_pv_input_kw = self._float(self.max_pv_input_field, DEFAULT_MAX_PV_INPUT)
        app.state.inverter_max_pv_charging_kw = self._float(self.max_pv_charging_field, DEFAULT_MAX_PV_CHARGING)
        app.state.inverter_max_battery_charge_kw = self._float(
            self.max_battery_charge_field, DEFAULT_MAX_BATTERY_CHARGE,
        )
        app.state.inverter_max_battery_discharge_kw = self._float(
            self.max_battery_discharge_field, DEFAULT_MAX_BATTERY_DISCHARGE,
        )
        app.state.inverter_efficiency_pct = self._float(
            self.inverter_efficiency_field, DEFAULT_INVERTER_EFFICIENCY_PCT,
        )

    def get_report_data(self) -> dict:
        return {
            "rated_power_kw": self._recommended_kw(),
            "max_pv_input_kw": self._float(self.max_pv_input_field, DEFAULT_MAX_PV_INPUT),
            "max_pv_charging_kw": self._float(self.max_pv_charging_field, DEFAULT_MAX_PV_CHARGING),
            "max_battery_charge_kw": self._float(self.max_battery_charge_field, DEFAULT_MAX_BATTERY_CHARGE),
            "max_battery_discharge_kw": self._float(
                self.max_battery_discharge_field, DEFAULT_MAX_BATTERY_DISCHARGE,
            ),
            "efficiency_pct": self._float(self.inverter_efficiency_field, DEFAULT_INVERTER_EFFICIENCY_PCT),
            "warnings": self._warning_items(),
        }

    def collect_state(self) -> dict:
        return {
            "max_pv_input_kw": self._float(self.max_pv_input_field, DEFAULT_MAX_PV_INPUT),
            "max_pv_charging_kw": self._float(self.max_pv_charging_field, DEFAULT_MAX_PV_CHARGING),
            "max_battery_charge_kw": self._float(self.max_battery_charge_field, DEFAULT_MAX_BATTERY_CHARGE),
            "max_battery_discharge_kw": self._float(
                self.max_battery_discharge_field, DEFAULT_MAX_BATTERY_DISCHARGE,
            ),
            "efficiency_pct": self._float(self.inverter_efficiency_field, DEFAULT_INVERTER_EFFICIENCY_PCT),
        }

    def apply_state(self, data: dict) -> None:
        self.max_pv_input_field.text = f"{data.get('max_pv_input_kw', DEFAULT_MAX_PV_INPUT):.2f}"
        self.max_pv_charging_field.text = f"{data.get('max_pv_charging_kw', DEFAULT_MAX_PV_CHARGING):.2f}"
        self.max_battery_charge_field.text = f"{data.get('max_battery_charge_kw', DEFAULT_MAX_BATTERY_CHARGE):.2f}"
        self.max_battery_discharge_field.text = (
            f"{data.get('max_battery_discharge_kw', DEFAULT_MAX_BATTERY_DISCHARGE):.2f}"
        )
        self.inverter_efficiency_field.text = (
            f"{data.get('efficiency_pct', DEFAULT_INVERTER_EFFICIENCY_PCT):.1f}"
        )
        self._recalculate_recommendation()

    def _show_calculation(self) -> None:
        required_kw = self._required_kw()
        recommended = self._recommended_kw()
        text = (
            "Recommended Inverter = higher of Peak Hourly Load and PV Capacity, rounded up\n"
            "to the nearest available spec (matches the Solar tab's auto-selected array size)\n\n"
            f"Peak Hourly Load = {self.peak_hourly_kwh:.2f} kW\n"
            f"PV Capacity = {self.pv_capacity_kw:.2f} kW\n"
            f"= max({self.peak_hourly_kwh:.2f}, {self.pv_capacity_kw:.2f}), rounded up\n"
            f"= {recommended:.2f} kW"
        )
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="Recommended Inverter - Calculation", text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "battery"

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "simulation"
