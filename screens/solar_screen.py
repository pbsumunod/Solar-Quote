"""Solar Sizing screen (ported from the desktop app's ui/solar.py).

Simplified from the original two-field-catalog design: the app now auto-picks the
solar array's kWp rating from the same fixed inverter catalog (logic.calculations
.INVERTER_KW_TIERS) that System Design auto-picks the inverter from, sized to the
higher of the computed solar requirement and the peak hourly load -- so the panel
array and the inverter always land on the exact same kW spec, with no separate
panel-wattage/panel-count fields to fill in. The underlying sizing formula is
unchanged (logic/calculations.py); SHOW CALCULATION still exposes it for anyone who
wants to see the math.
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

from logic.calculations import (
    INVERTER_KW_TIERS,
    daily_consumption_kwh,
    required_solar_kw,
    round_up_to_standard_size,
)
from ui_style import (
    ACCENT, TEXT_DARK, about_button, header_actions, keep_focused_field_visible, m3_field, nav_row, save_button, save_current_project, screen_header, section_card, tonal_button, with_bg,
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
        self._build_ui()
        self._recalculate()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Solar Sizing", step=3, on_back=self._go_back,
            right_widget=header_actions(about_button(self._go_about), save_button(on_release=save_current_project)),
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
            "Efficiency %", icon="percent", input_filter="float", text=f"{DEFAULT_SYSTEM_EFFICIENCY_PCT:.1f}",
        )
        for f in (self.peak_sun_hours_field, self.efficiency_field):
            f.bind(text=lambda *_a: self._recalculate())
            assumptions_row.add_widget(f)
        assumptions_card.add_widget(assumptions_row)
        form.add_widget(assumptions_card)

        result_card = section_card("solar-power", "Recommended Solar Array")
        result_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.recommended_label = with_bg(MDLabel(
            text="-- kWp", bold=True, theme_text_color="Custom", text_color=ACCENT,
        ))
        result_row.add_widget(self.recommended_label)
        result_row.add_widget(tonal_button(
            "SHOW CALCULATION", on_release=self._show_calculation, size_hint_x=None, width=dp(170),
        ))
        result_card.add_widget(result_row)
        self.note_label = with_bg(MDLabel(
            text="Matches your inverter's auto-selected size (see System Design).",
            theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None, height=dp(24),
        ))
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
        self._recalculate()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        try:
            return float(field.text)
        except ValueError:
            return default

    def _required_kw(self) -> float:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        peak_sun_hours = self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT)
        return required_solar_kw(daily_kwh, peak_sun_hours, efficiency_pct)

    def _recommended_kw(self) -> float:
        system_kw = max(self.peak_hourly_kwh, self._required_kw())
        return round_up_to_standard_size(system_kw, INVERTER_KW_TIERS) or 0.0

    def _recalculate(self) -> None:
        recommended = self._recommended_kw()
        self.recommended_label.text = f"{recommended:.2f} kWp"

        app = MDApp.get_running_app()
        app.state.peak_sun_hours = self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS)
        app.state.efficiency_pct = self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT)
        app.state.solar_total_kw = recommended

    def get_report_data(self) -> dict:
        return {
            "peak_sun_hours": self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS),
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT),
            "required_kw": self._required_kw(),
            "total_kw": self._recommended_kw(),
        }

    def collect_state(self) -> dict:
        return {
            "peak_sun_hours": self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS),
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT),
        }

    def apply_state(self, data: dict) -> None:
        self.peak_sun_hours_field.text = f"{data.get('peak_sun_hours', DEFAULT_PEAK_SUN_HOURS):.2f}"
        self.efficiency_field.text = f"{data.get('efficiency_pct', DEFAULT_SYSTEM_EFFICIENCY_PCT):.1f}"
        self._recalculate()

    def _show_calculation(self) -> None:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        peak_sun_hours = self._float(self.peak_sun_hours_field, DEFAULT_PEAK_SUN_HOURS)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_SYSTEM_EFFICIENCY_PCT)
        required_kw = self._required_kw()
        recommended = self._recommended_kw()
        text = (
            "Required Solar kW = Daily Energy Requirement / Peak Sun Hours / System Efficiency\n\n"
            f"= {daily_kwh:.2f} kWh / {peak_sun_hours:.2f} hrs / {efficiency_pct:.0f}%\n"
            f"= {required_kw:.2f} kWp\n\n"
            "System Size = higher of Required Solar kW and Peak Hourly Load, rounded up to the "
            "nearest available spec -- this becomes both your panel array size and your inverter size:\n"
            f"= max({required_kw:.2f}, {self.peak_hourly_kwh:.2f} kW), rounded up\n"
            f"= {recommended:.2f} kWp"
        )
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
        app = MDApp.get_running_app()
        app.root.current = "battery"
