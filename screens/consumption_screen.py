"""Consumption screen (ported from the desktop app's ui/consumption.py).

The 24-row editable QTableWidget becomes a GridLayout in a ScrollView (simpler than
RecycleView for just 24 rows). The embedded matplotlib bar chart is explicitly
deferred per the Phase 1 plan -- a placeholder label stands in for it. All the
actual math (daily/day/night/peak, per-hour kWh) still comes from the ported
logic/calculations.py, unchanged from the desktop version.
"""

from kivy.metrics import dp
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from logic.calculations import (
    HOUR_LABELS,
    daily_consumption_kwh,
    default_hourly_percentages,
    hourly_kwh_from_percentages,
    split_day_night_kwh,
)
from ui_style import ACCENT, ACCENT_LIGHT, HEADER_BG, NEAR_WHITE, ROW_LINE, TEXT_DARK, WHITE, framed_label, top_app_bar


class ConsumptionScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "consumption"
        self.monthly_kwh = 0.0
        self.daytime_pct = 70
        self.hourly_pct = default_hourly_percentages(self.daytime_pct)
        self._pct_fields: list[MDTextField] = []
        self._kwh_labels: list[MDLabel] = []
        self._updating = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(top_app_bar("Consumption", on_back=self._go_back))

        summary = MDBoxLayout(spacing=dp(4), padding=(dp(4), dp(2)), size_hint_y=None, height=dp(56))
        self.total_label = self._make_stat(summary, "Total Daily")
        self.day_label = self._make_stat(summary, "Daytime")
        self.night_label = self._make_stat(summary, "Nighttime")
        self.peak_label = self._make_stat(summary, "Peak Hourly")
        root.add_widget(summary)

        header_row = MDBoxLayout(spacing=dp(8), padding=(dp(8), 0), size_hint_y=None, height=dp(36))
        self.total_pct_label = MDLabel(
            text="Total: 100.00% (must equal 100%)", theme_text_color="Custom", text_color=TEXT_DARK,
        )
        header_row.add_widget(self.total_pct_label)
        reset_btn = MDRaisedButton(
            text="RESET", md_bg_color=ACCENT, text_color=WHITE, on_release=lambda *_: self._reset_to_default(),
        )
        header_row.add_widget(reset_btn)
        root.add_widget(header_row)

        # Daytime (first 12 hours) and nighttime (last 12) sit side by side instead of one
        # 24-row column -- halves the scroll length and mirrors the day/night grouping
        # used everywhere else in the app (colors, ratio split, etc).
        scroll = ScrollView()
        columns = MDBoxLayout(spacing=dp(8), padding=dp(4), size_hint_y=None)
        columns.bind(minimum_height=columns.setter("height"))
        day_col = self._build_hour_column("Daytime (6AM-5PM)", range(0, 12))
        night_col = self._build_hour_column("Nighttime (6PM-5AM)", range(12, 24))
        columns.add_widget(day_col)
        columns.add_widget(night_col)
        scroll.add_widget(columns)
        root.add_widget(scroll)

        root.add_widget(MDLabel(
            text="Chart view coming soon", halign="center", size_hint_y=None, height=dp(32),
            theme_text_color="Custom", text_color=TEXT_DARK,
        ))

        next_btn = MDRaisedButton(
            text="Next: Solar Sizing", size_hint_x=1, size_hint_y=None, height=dp(40),
            md_bg_color=ACCENT, text_color=WHITE, on_release=lambda *_: self._go_next(),
        )
        root.add_widget(next_btn)

        self.add_widget(root)

    def _build_hour_column(self, title: str, indices: range) -> MDBoxLayout:
        col = MDBoxLayout(orientation="vertical", size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        # Solid green group-header bar spanning the Hour/%/kWh sub-columns below it,
        # echoing the reference table's grouped header row (e.g. "Fixed" over "<1y/>1y").
        col.add_widget(framed_label(title, dp(26), bold=True, bg=ACCENT, fg=WHITE))

        row_h = dp(36)
        grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(1), padding=dp(1),
                           row_default_height=row_h, row_force_default=True)
        grid.bind(minimum_height=grid.setter("height"))

        grid.add_widget(framed_label("Hour", row_h, bold=True, bg=HEADER_BG))
        grid.add_widget(framed_label("%", row_h, bold=True, bg=HEADER_BG))
        grid.add_widget(framed_label("kWh", row_h, bold=True, bg=HEADER_BG))
        for i in indices:
            # Hour column: light green. %/kWh columns: near-white (~10% green tint) --
            # each cell owns an explicit opaque background, nothing relies on bleed-through.
            grid.add_widget(framed_label(HOUR_LABELS[i], row_h, bg=ACCENT_LIGHT))
            pct_field = MDTextField(
                text=f"{self.hourly_pct[i]:.2f}", input_filter="float",
                font_size="13sp", size_hint_y=None, height=row_h,
                mode="fill", fill_color_normal=NEAR_WHITE, fill_color_focus=WHITE,
                foreground_color=TEXT_DARK, line_color_normal=ROW_LINE, line_color_focus=ACCENT,
            )
            pct_field.bind(text=lambda _inst, val, idx=i: self._on_pct_changed(idx, val))
            grid.add_widget(pct_field)
            self._pct_fields.append(pct_field)
            kwh_label = framed_label("0.00", row_h, bg=NEAR_WHITE)
            grid.add_widget(kwh_label)
            self._kwh_labels.append(kwh_label)
        col.add_widget(grid)
        return col

    def _make_stat(self, row: MDBoxLayout, title: str) -> MDLabel:
        box = MDBoxLayout(orientation="vertical")
        box.add_widget(MDLabel(text=title, halign="center", theme_text_color="Custom", text_color=TEXT_DARK))
        value_label = MDLabel(text="-- kWh", bold=True, halign="center", theme_text_color="Custom", text_color=ACCENT)
        box.add_widget(value_label)
        row.add_widget(box)
        return value_label

    def on_pre_enter(self, *_args) -> None:
        app = MDApp.get_running_app()
        project = app.state.project
        ratio_changed = project.daytime_ratio_pct != self.daytime_pct
        self.monthly_kwh = project.monthly_kwh
        self.daytime_pct = project.daytime_ratio_pct
        if ratio_changed:
            self.hourly_pct = default_hourly_percentages(self.daytime_pct)
            self._refresh_table()
        self._refresh_kwh_column()
        self._refresh_summary()

    def _refresh_table(self) -> None:
        self._updating = True
        for i, field in enumerate(self._pct_fields):
            field.text = f"{self.hourly_pct[i]:.2f}"
        self._updating = False

    def _on_pct_changed(self, idx: int, value: str) -> None:
        if self._updating:
            return
        try:
            self.hourly_pct[idx] = max(0.0, float(value))
        except ValueError:
            return
        self._refresh_kwh_column()
        self._refresh_summary()

    def _refresh_kwh_column(self) -> None:
        hourly_kwh = hourly_kwh_from_percentages(self.monthly_kwh, self.hourly_pct)
        for i, kwh in enumerate(hourly_kwh):
            self._kwh_labels[i].text = f"{kwh:.2f}"
        total = sum(self.hourly_pct)
        self.total_pct_label.text = f"Total: {total:.2f}% (must equal 100%)"

    def _refresh_summary(self) -> None:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        day_kwh, night_kwh = split_day_night_kwh(daily_kwh, self.daytime_pct)
        hourly_kwh = hourly_kwh_from_percentages(self.monthly_kwh, self.hourly_pct)
        peak = max(hourly_kwh) if hourly_kwh else 0.0
        self.total_label.text = f"{daily_kwh:.2f} kWh"
        self.day_label.text = f"{day_kwh:.2f} kWh"
        self.night_label.text = f"{night_kwh:.2f} kWh"
        self.peak_label.text = f"{peak:.2f} kWh"

        app = MDApp.get_running_app()
        app.state.hourly_pct = list(self.hourly_pct)
        app.state.peak_hourly_kwh = peak

    def get_report_data(self) -> dict:
        daily_kwh = daily_consumption_kwh(self.monthly_kwh)
        day_kwh, night_kwh = split_day_night_kwh(daily_kwh, self.daytime_pct)
        hourly_kwh = hourly_kwh_from_percentages(self.monthly_kwh, self.hourly_pct)
        return {
            "daily_kwh": daily_kwh,
            "day_kwh": day_kwh,
            "night_kwh": night_kwh,
            "peak_kwh": max(hourly_kwh) if hourly_kwh else 0.0,
            "hourly_kwh": hourly_kwh,
        }

    def _reset_to_default(self) -> None:
        self.hourly_pct = default_hourly_percentages(self.daytime_pct)
        self._refresh_table()
        self._refresh_kwh_column()
        self._refresh_summary()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "client"

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "solar"
