"""Automatic inverter and battery compatibility summary."""

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from logic.equipment import refresh_equipment_design
from ui_style import (
    ACCENT, TEXT_DARK, about_button, go_home, header_actions, icon_button,
    nav_row, save_button, save_current_project, screen_header, section_card,
    section_label, tonal_button, warning_row, with_bg,
)


class SystemDesignScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "system_design"
        self._dialog = None
        self._build_ui()
        self._recalculate_recommendation()

    def _build_ui(self):
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Auto System Design", step=5, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about),
                icon_button("home-outline", on_release=go_home, color=ACCENT),
                save_button(on_release=save_current_project)),
        ))
        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))
        card = section_card("flash-outline", "Automatically Selected Inverter")
        self.recommended_label = with_bg(MDLabel(text="-- kW", bold=True,
            theme_text_color="Custom", text_color=ACCENT, size_hint_y=None, height=dp(32)))
        card.add_widget(self.recommended_label)
        self.model_label = MDLabel(text="--", theme_text_color="Custom", text_color=TEXT_DARK,
                                  size_hint_y=None, height=dp(72))
        self.model_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                              texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(8)))
        card.add_widget(self.model_label)
        card.add_widget(tonal_button("SHOW CALCULATION", on_release=self._show_calculation))
        form.add_widget(card)
        limits_card = section_card("tune-variant", "Compatible Equipment Limits")
        self.limits_label = MDLabel(text="--", theme_text_color="Custom", text_color=TEXT_DARK,
                                   size_hint_y=None, height=dp(160))
        self.limits_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                               texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(8)))
        limits_card.add_widget(self.limits_label)
        form.add_widget(limits_card)
        form.add_widget(section_label("alert-outline", "Design Checks"))
        self.warnings_container = MDBoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None)
        self.warnings_container.bind(minimum_height=self.warnings_container.setter("height"))
        form.add_widget(self.warnings_container)
        summary = section_card("clipboard-text-outline", "Final Selected System")
        self.final_solar_label = self._summary_line(summary, "Solar DC")
        self.final_inverter_label = self._summary_line(summary, "Inverter AC")
        self.final_battery_label = self._summary_line(summary, "Battery")
        form.add_widget(summary)
        form.add_widget(nav_row(self._go_back, "Next: Simulation", self._go_next))
        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _summary_line(self, container, title):
        row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        row.add_widget(MDLabel(text=title, theme_text_color="Custom", text_color=TEXT_DARK, size_hint_x=0.3))
        label = with_bg(MDLabel(text="--", bold=True, theme_text_color="Custom", text_color=ACCENT))
        row.add_widget(label)
        container.add_widget(row)
        return label

    def _design(self):
        return refresh_equipment_design(MDApp.get_running_app().state)

    def on_pre_enter(self, *_args):
        self._recalculate_recommendation()

    def _required_kw(self):
        return self._design().required_inverter_kw

    def _recommended_kw(self):
        return self._design().inverter_rated_kw

    def _warning_items(self):
        design = self._design()
        if not design.feasible:
            return [(False, design.error)]
        items = [
            (True, f"AC rating {design.inverter_rated_kw:g} kW meets requirement {design.required_inverter_kw:.2f} kW."),
            (True, f"PV array {design.pv_capacity_kw:g} kWp is within {design.max_pv_input_kw:g} kW DC input rating."),
            (True, f"Battery: {design.battery_voltage_class}; voltage envelope and operating current checked." if design.storage_enabled else "Storage is disabled or nighttime demand is zero; no battery needed."),
            (False, "Planning estimate: measured peak/surge, BMS compatibility, PV strings and site commissioning still require verification."),
        ]
        if design.inverter_phase_count == 3:
            items.append((False, "Requires three-phase service; confirm site phase availability and phase load balance."))
        return items

    def _recalculate_recommendation(self):
        design = self._design()
        self.recommended_label.text = f"{design.inverter_rated_kw:g} kW AC" if design.feasible else "Design unavailable"
        self.model_label.text = f"{design.inverter_count} x {design.inverter_model}\n{design.inverter_phase_count}-phase planning selection; catalog reviewed {design.catalog_review_date}."
        self.limits_label.text = (
            f"PV input: {design.max_pv_input_kw:g} kW DC; DC/AC ratio: {design.dc_ac_ratio:.2f}\n"
            f"PV conversion limit: {design.max_pv_conversion_kw:.2f} kW DC\n"
            f"Inverter efficiency: {design.inverter_efficiency_pct:g}%\n"
            f"PV battery charging: {design.max_pv_charging_kw:.2f} kW DC\n"
            f"Battery charge: {design.max_battery_charge_kw:.2f} kW DC / {design.battery_charge_current_a:g} A\n"
            f"Battery discharge: {design.max_battery_discharge_kw:.2f} kW AC / {design.battery_discharge_current_a:g} A\n"
            f"Bank voltage: {design.battery_voltage_min:g}-{design.battery_voltage_max:g} V\n"
            f"Grid export supported: {'Yes' if design.supports_grid_export else 'No (1 kW planning assembly)'}"
        )
        self.warnings_container.clear_widgets()
        for ok, text in self._warning_items():
            self.warnings_container.add_widget(warning_row(ok, text))
        self.final_solar_label.text = f"{design.pv_capacity_kw:.2f} kWp DC"
        self.final_inverter_label.text = f"{design.inverter_rated_kw:g} kW AC"
        self.final_battery_label.text = f"{design.battery_total_kwh:.2f} kWh / {design.battery_voltage:g} V"

    def get_report_data(self):
        design = self._design()
        return {
            "rated_power_kw": design.inverter_rated_kw,
            "max_pv_input_kw": design.max_pv_input_kw,
            "max_pv_conversion_kw": design.max_pv_conversion_kw,
            "max_pv_charging_kw": design.max_pv_charging_kw,
            "max_battery_charge_kw": design.max_battery_charge_kw,
            "max_battery_discharge_kw": design.max_battery_discharge_kw,
            "efficiency_pct": design.inverter_efficiency_pct,
            "warnings": self._warning_items(),
            "equipment": design.as_dict(),
            "model": design.inverter_model,
            "unit_count": design.inverter_count,
            "phase_count": design.inverter_phase_count,
            "dc_ac_ratio": design.dc_ac_ratio,
            "sources": design.sources,
            "notes": design.notes,
            "selection_error": design.error,
            "supports_grid_export": design.supports_grid_export,
        }

    def collect_state(self):
        data = self.get_report_data()
        return {key: data[key] for key in ("max_pv_input_kw", "max_pv_charging_kw", "max_battery_charge_kw",
                "max_battery_discharge_kw", "efficiency_pct", "selection_error")}

    def apply_state(self, _data):
        # Legacy manually entered limits cannot override a compatible automatic selection.
        self._recalculate_recommendation()

    def _show_calculation(self):
        design = self._design()
        text = (
            "AC requirement = max(peak load x 1.25, DC array / 1.5, expected peak PV AC).\n"
            "Select the smallest catalog rating that also meets supplied surge demand and compatible battery power/capacity.\n\n"
            f"Peak: {design.peak_load_kw:.2f} kW; surge input/estimate: {design.surge_load_kw:.2f} kW.\n"
            f"Required AC: {design.required_inverter_kw:.2f} kW; selected: {design.inverter_rated_kw:g} kW.\n"
            f"PV DC: {design.pv_capacity_kw:.2f} kWp; ratio: {design.dc_ac_ratio:.2f}.\n"
            "Battery power uses current x minimum operating bank voltage; series modules raise voltage, parallel strings raise current."
        ) if design.feasible else design.error
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(title="Auto Selection Calculation", text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())])
        self._dialog.open()

    def _go_back(self):
        MDApp.get_running_app().root.current = "battery"

    def _go_about(self):
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self):
        design = self._design()
        if not design.feasible:
            self._show_calculation()
            return
        MDApp.get_running_app().root.current = "simulation"
