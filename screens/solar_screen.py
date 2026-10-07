"""Independent DC PV sizing from the authoritative automatic equipment design.

Manual peak sun hours are estimates. Imported resource metadata and monthly values
remain attached until the user replaces the peak sun hours manually.
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

from logic.calculations import daily_consumption_kwh
from logic.equipment import refresh_equipment_design
from logic.quote_validation import finite_float_or, live_float_or
from logic.solar_assumptions import MANUAL_RESOURCE_SOURCE, normalized_resource_state, resource_matches_project
from ui_style import (
    ACCENT, TEXT_DARK, about_button, go_home, header_actions, icon_button, keep_focused_field_visible, m3_field, nav_row, save_button, save_current_project, screen_header, section_card, tonal_button, with_bg,
)

DEFAULT_PEAK_SUN_HOURS = 4.5
DEFAULT_SYSTEM_EFFICIENCY_PCT = 80.0


class SolarScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "solar"
        self.monthly_kwh = 0.0
        self.peak_hourly_kwh = 0.0
        self._dialog: MDDialog | None = None
        self._applying_state = False
        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Solar Sizing", step=3, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about), icon_button("home-outline", on_release=go_home, color=ACCENT), save_button(on_release=save_current_project)),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        assumptions_card = section_card("weather-sunny", "Solar System Assumptions")
        assumptions_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.peak_sun_hours_field = m3_field(
            "Peak Sun Hours", icon="weather-sunny", input_filter="float", text=f"{DEFAULT_PEAK_SUN_HOURS:.2f}",
        )
        self.efficiency_field = m3_field(
            "PV Efficiency % (excludes inverter)", icon="percent", input_filter="float", text=f"{DEFAULT_SYSTEM_EFFICIENCY_PCT:.1f}",
        )
        self.peak_sun_hours_field.bind(text=self._on_sun_hours_changed)
        self.efficiency_field.bind(text=lambda *_a: self._recalculate())
        for f in (self.peak_sun_hours_field, self.efficiency_field):
            assumptions_row.add_widget(f)
        assumptions_card.add_widget(assumptions_row)
        form.add_widget(assumptions_card)

        result_card = section_card("solar-power", "Recommended Solar Array")
        result_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.recommended_label = with_bg(MDLabel(
            text="-- kWp", bold=True, theme_text_color="Custom", text_color=ACCENT, size_hint_y=None,
        ))
        result_row.add_widget(self.recommended_label)
        calculation_button = tonal_button(
            "SHOW CALCULATION", on_release=self._show_calculation, size_hint_x=None, width=dp(170),
        )
        result_row.add_widget(calculation_button)
        self.recommended_label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)),
                                    texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(8)))
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
        self.note_label = with_bg(MDLabel(
            text="DC array sized independently from the AC inverter. Planning estimate.",
            theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None, height=dp(96),
        ))
        self.note_label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)),
                             texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(8)))
        result_card.add_widget(self.note_label)
        form.add_widget(result_card)

        form.add_widget(nav_row(self._go_back, "Next: Battery Sizing", self._go_next))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        self.monthly_kwh = app.state.project.monthly_kwh
        self.peak_hourly_kwh = app.state.peak_hourly_kwh
        state = app.state
        if state.resource_is_all_sky and not resource_matches_project(state.resource_metadata, state.project):
            self._clear_resource("Site or roof inputs changed; old solar resource cleared. Reload the site resource or use the manual planning estimate.", reset_psh=True)
        self._recalculate()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        return live_float_or(field.text, default)

    def _on_sun_hours_changed(self, *_args):
        if not self._applying_state:
            self._clear_resource()
        self._recalculate()

    def _clear_resource(self, warning="", reset_psh=False):
        state = MDApp.get_running_app().state
        state.resource_is_all_sky = False
        state.resource_source = MANUAL_RESOURCE_SOURCE
        state.monthly_peak_sun_hours = []
        state.resource_coordinates = None
        state.resource_metadata = {}
        state.resource_warning = warning
        if reset_psh:
            self._applying_state = True
            try:
                self.peak_sun_hours_field.text = f"{DEFAULT_PEAK_SUN_HOURS:.6f}"
                state.peak_sun_hours = DEFAULT_PEAK_SUN_HOURS
            finally:
                self._applying_state = False

    def set_resource_data(self, resource: dict, coordinates=None):
        state = MDApp.get_running_app().state
        self._applying_state = True
        try:
            state.resource_source = resource["source"]
            state.resource_is_all_sky = True
            state.monthly_peak_sun_hours = list(resource.get("monthly_peak_sun_hours", []))
            state.resource_coordinates = coordinates
            state.resource_metadata = {key: value for key, value in resource.items()
                                       if key not in ("annual_peak_sun_hours", "monthly_peak_sun_hours")}
            state.resource_warning = ""
            self.peak_sun_hours_field.text = f"{resource['annual_peak_sun_hours']:.6f}"
        finally:
            self._applying_state = False
        self._recalculate()

    def _required_kw(self) -> float:
        return self._design().pv_required_kw

    def _design(self):
        state = MDApp.get_running_app().state
        state.peak_sun_hours = self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS)
        state.efficiency_pct = self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT)
        return refresh_equipment_design(state)

    def _recommended_kw(self) -> float:
        return self._design().pv_capacity_kw

    def _recalculate(self) -> None:
        app = MDApp.get_running_app()
        design = self._design()
        self.recommended_label.text = f"{design.pv_capacity_kw:.2f} kWp DC" if design.feasible else "Design unavailable"
        self.note_label.text = (f"Auto inverter: {design.inverter_rated_kw:g} kW AC; DC/AC ratio {design.dc_ac_ratio:.2f}.\n"
                                f"Resource: {app.state.resource_source}. Planning estimate."
                                if design.feasible else design.error)
        if app.state.resource_warning:
            self.note_label.text += "\n" + app.state.resource_warning

    def get_report_data(self) -> dict:
        design = self._design()
        return {
            "peak_sun_hours": self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS),
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT),
            "required_kw": self._required_kw(),
            "total_kw": self._recommended_kw(),
            "dc_ac_ratio": design.dc_ac_ratio,
            "equipment": design.as_dict(),
            "resource_source": MDApp.get_running_app().state.resource_source,
            "resource_warning": MDApp.get_running_app().state.resource_warning,
            "selection_error": design.error,
            "efficiency_convention": "PV losses exclude separately modeled inverter conversion.",
        }

    def collect_state(self) -> dict:
        state = MDApp.get_running_app().state
        return {
            "peak_sun_hours": self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS),
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT),
            "selection_error": self._design().error,
            "resource_source": state.resource_source,
            "resource_is_all_sky": state.resource_is_all_sky,
            "resource_coordinates": state.resource_coordinates,
            "monthly_peak_sun_hours": list(state.monthly_peak_sun_hours),
            "resource_metadata": dict(state.resource_metadata),
            "resource_warning": state.resource_warning,
        }

    def apply_state(self, data: dict) -> None:
        state = MDApp.get_running_app().state
        resource = normalized_resource_state(data)
        self._applying_state = True
        try:
            for key, value in resource.items():
                setattr(state, key, value)
            self.peak_sun_hours_field.text = f"{resource['peak_sun_hours']:.6f}"
            efficiency = finite_float_or(data.get('efficiency_pct'), DEFAULT_SYSTEM_EFFICIENCY_PCT)
            self.efficiency_field.text = f"{efficiency:.6f}"
        finally:
            self._applying_state = False
        self._recalculate()

    def _show_calculation(self) -> None:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        peak_sun_hours = self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT)
        required_kw = self._required_kw()
        recommended = self._recommended_kw()
        design = self._design()
        text = (
            "Daily load = monthly kWh x 12 / 365.\n"
            "Required DC PV = (day load + stored night load / battery efficiency) / "
            "inverter efficiency / peak sun hours / PV efficiency.\n\n"
            f"Daily load: {daily_kwh:.2f} kWh; PSH: {peak_sun_hours:.2f}; PV efficiency: {efficiency_pct:.1f}%.\n"
            f"Required: {required_kw:.2f} kWp DC; array rounded up in 0.1 kWp planning increments: {recommended:.2f} kWp.\n"
            f"AC inverter: {design.inverter_rated_kw:g} kW; DC/AC ratio: {design.dc_ac_ratio:.2f}.\n"
            "Inverter is sized separately for peak load + 25% headroom, expected PV output and supplied surge demand."
        ) if design.feasible else design.error
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="Recommended Solar Array - Calculation", text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "consumption"

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        if not self._design().feasible:
            self._show_calculation()
            return
        app = MDApp.get_running_app()
        app.root.current = "battery"
