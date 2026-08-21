"""Battery screen (ported from the desktop app's ui/battery.py).

Simplified from the original unit-capacity x count design: the app now auto-picks
the total battery capacity from a fixed catalog (logic.calculations
.BATTERY_CAPACITY_TIERS_KWH), rounded up to the next tier -- no more manually
entering a per-unit capacity and a battery count. Battery voltage stays as a plain
assumption field (it doesn't feed any calculation, just informational for whoever
specs the physical hardware). All sizing math is unchanged, from the ported
logic/calculations.py; SHOW CALCULATION still exposes it.
"""

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from logic.calculations import (
    BATTERY_CAPACITY_TIERS_KWH,
    battery_usable_capacity_kwh,
    daily_consumption_kwh,
    required_battery_kwh,
    round_up_to_standard_size,
    split_day_night_kwh,
)
from ui_style import ACCENT, TEXT_DARK, WHITE, green_field, top_app_bar, with_bg

DEFAULT_BATTERY_DOD_PCT = 80.0
DEFAULT_BATTERY_EFFICIENCY_PCT = 90.0
DEFAULT_BATTERY_VOLTAGE = 48.0


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
        root.add_widget(top_app_bar("Battery Sizing", on_back=self._go_back))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        form.add_widget(self._section_label("Battery Assumptions"))
        assumptions_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        self.dod_field = green_field(
            hint_text="Depth of Discharge %", input_filter="float", text=f"{DEFAULT_BATTERY_DOD_PCT:.1f}",
        )
        self.efficiency_field = green_field(
            hint_text="Round Trip Efficiency %", input_filter="float",
            text=f"{DEFAULT_BATTERY_EFFICIENCY_PCT:.1f}",
        )
        for f in (self.dod_field, self.efficiency_field):
            f.bind(text=lambda *_a: self._recalculate())
            assumptions_row.add_widget(f)
        form.add_widget(assumptions_row)

        self.voltage_field = green_field(
            hint_text="Battery Voltage (V)", input_filter="float", text=f"{DEFAULT_BATTERY_VOLTAGE:.1f}",
        )
        self.voltage_field.bind(text=lambda *_a: self._recalculate())
        form.add_widget(self.voltage_field)

        form.add_widget(self._section_label("Recommended Battery Capacity"))

        self.nighttime_context_label = with_bg(MDLabel(
            text="Nighttime Consumption: -- kWh", theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None, height=dp(24),
        ))
        form.add_widget(self.nighttime_context_label)

        result_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.recommended_label = with_bg(MDLabel(
            text="-- kWh", bold=True, theme_text_color="Custom", text_color=ACCENT,
        ))
        result_row.add_widget(self.recommended_label)
        show_calc_btn = MDRaisedButton(
            text="SHOW CALCULATION", md_bg_color=ACCENT, text_color=WHITE,
            on_release=lambda *_: self._show_calculation(),
        )
        result_row.add_widget(show_calc_btn)
        form.add_widget(result_row)

        self.usable_capacity_label = with_bg(MDLabel(
            text="Usable Battery Capacity: -- kWh", bold=True, theme_text_color="Custom", text_color=ACCENT,
            size_hint_y=None, height=dp(28),
        ))
        form.add_widget(self.usable_capacity_label)

        next_btn = MDRaisedButton(
            text="Next: System Design", size_hint_x=1, md_bg_color=ACCENT, text_color=WHITE,
            on_release=lambda *_: self._go_next(),
        )
        form.add_widget(next_btn)

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _section_label(self, text: str) -> MDLabel:
        return MDLabel(
            text=text, bold=True, size_hint_y=None, height=dp(24),
            theme_text_color="Custom", text_color=TEXT_DARK,
        )

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        self.monthly_kwh = app.state.project.monthly_kwh
        self.daytime_pct = app.state.project.daytime_ratio_pct
        self._recalculate()

    def _float(self, field: MDTextField, default: float = 0.0) -> float:
        try:
            return float(field.text)
        except ValueError:
            return default

    def _nighttime_kwh(self) -> float:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        _, night_kwh = split_day_night_kwh(daily_kwh, self.daytime_pct)
        return night_kwh

    def _required_kwh(self) -> float:
        night_kwh = self._nighttime_kwh()
        dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT)
        return required_battery_kwh(night_kwh, dod_pct, efficiency_pct)

    def _recommended_kwh(self) -> float:
        return round_up_to_standard_size(self._required_kwh(), BATTERY_CAPACITY_TIERS_KWH) or 0.0

    def _recalculate(self) -> None:
        night_kwh = self._nighttime_kwh()
        self.nighttime_context_label.text = f"Nighttime Consumption: {night_kwh:.2f} kWh"

        recommended = self._recommended_kwh()
        self.recommended_label.text = f"{recommended:.2f} kWh"

        dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        usable_kwh = battery_usable_capacity_kwh(recommended, dod_pct)
        self.usable_capacity_label.text = f"Usable Battery Capacity: {usable_kwh:.2f} kWh"

        app = MDApp.get_running_app()
        app.state.battery_dod_pct = dod_pct
        app.state.battery_efficiency_pct = self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT)
        app.state.battery_voltage = self._float(self.voltage_field, DEFAULT_BATTERY_VOLTAGE)
        app.state.battery_total_kwh = recommended
        app.state.battery_usable_kwh = usable_kwh

    def get_report_data(self) -> dict:
        dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        recommended = self._recommended_kwh()
        return {
            "dod_pct": dod_pct,
            "efficiency_pct": self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT),
            "required_kwh": self._required_kwh(),
            "voltage": self._float(self.voltage_field, DEFAULT_BATTERY_VOLTAGE),
            "total_kwh": recommended,
            "usable_kwh": battery_usable_capacity_kwh(recommended, dod_pct),
        }

    def _show_calculation(self) -> None:
        night_kwh = self._nighttime_kwh()
        dod_pct = self._float(self.dod_field, DEFAULT_BATTERY_DOD_PCT)
        efficiency_pct = self._float(self.efficiency_field, DEFAULT_BATTERY_EFFICIENCY_PCT)
        required_kwh = self._required_kwh()
        recommended = self._recommended_kwh()
        text = (
            "Required Battery Capacity = Nighttime Consumption / Battery DOD / Battery Efficiency\n\n"
            f"= {night_kwh:.2f} kWh / {dod_pct:.0f}% / {efficiency_pct:.0f}%\n"
            f"= {required_kwh:.2f} kWh\n\n"
            f"Rounded up to the nearest available spec = {recommended:.2f} kWh"
        )
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

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "system_design"
