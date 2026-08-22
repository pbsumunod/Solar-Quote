"""Consumption screen (ported from the desktop app's ui/consumption.py).

The 24-row editable QTableWidget becomes a GridLayout in a ScrollView (simpler than
RecycleView for just 24 rows). The embedded matplotlib bar chart is explicitly
deferred per the Phase 1 plan -- a placeholder label stands in for it. All the
actual math (daily/day/night/peak, per-hour kWh) still comes from the ported
logic/calculations.py, unchanged from the desktop version.
"""

from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
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
from ui_style import (
    ACCENT, ACCENT_LIGHT, HEADER_BG, NEAR_WHITE, ON_SURFACE_VARIANT, ROW_LINE, TEXT_DARK, WHITE,
    about_button, framed_label, nav_row, screen_header, section_card, section_label,
    stat_title_label, tonal_button,
)
from widgets.bar_chart import BarChart


class _PctField(MDTextField):
    """MDTextField subclass for the % column cells.

    KivyMD's own textfield.kv binds both `padding` (24dp top / 8dp bottom in
    "fill" mode, reserved for a floating hint label even with none set) and
    `height` (`height: self.minimum_height`, so the field always shrinks to
    fit its own text) to live kv expressions -- not one-time defaults, so a
    plain Python assignment to either gets silently overwritten again within
    a fraction of a second (confirmed by reading each back after forcing it).
    That's harmless for `height` inside a plain BoxLayout/GridLayout row sized
    to fit its content, but this field sits in a GridLayout row with a FIXED
    row_default_height, and GridLayout only resizes a child that leaves its
    own size_hint unset -- with size_hint_y=None here (so this field can have
    an explicit height at all), the grid just repositions the field at the
    bottom of its row slot without stretching it, so a field silently shrunk
    to `minimum_height` renders as an undersized box hugging the row's bottom
    edge instead of filling it. Re-binding our own fixed values back to both
    `padding` and `height` whenever KivyMD's own bindings fire wins the race,
    the same way, for the same reason, on both properties.

    With height forced to a fixed row height taller than a single line of
    text, top/bottom padding also has to be forced -- Kivy's TextInput always
    draws its (single) line starting right below the top padding, it doesn't
    center text in unused vertical space on its own. Vertical padding is
    computed from the field's own line_height so the text sits centered in
    whatever height is forced, rather than a hand-picked constant that would
    only be correct for this exact font size/row height combination.
    """

    _side_padding = dp(4)

    def __init__(self, **kwargs):
        self._fixed_height = kwargs.get("height", dp(56))
        super().__init__(**kwargs)
        self._apply_fixed_padding()
        self.height = self._fixed_height
        self.bind(padding=self._enforce_padding, height=self._enforce_height, line_height=self._apply_fixed_padding)

    def _target_padding(self) -> list:
        vertical = max(self._side_padding, (self._fixed_height - self.line_height) / 2)
        return [self._side_padding, vertical, self._side_padding, vertical]

    def _apply_fixed_padding(self, *_args):
        self.padding = self._target_padding()

    def _enforce_padding(self, _instance, value):
        target = self._target_padding()
        if list(value) != target:
            self.padding = target

    def _enforce_height(self, _instance, value):
        if value != self._fixed_height:
            self.height = self._fixed_height


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
        root.add_widget(screen_header(
            "Consumption", step=2, on_back=self._go_back, right_widget=about_button(self._go_about),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        summary_card = section_card("chart-bell-curve-cumulative", "Daily Consumption Summary")
        summary = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(56))
        self.total_label = self._make_stat(summary, "Total Daily")
        self.day_label = self._make_stat(summary, "Daytime")
        self.night_label = self._make_stat(summary, "Nighttime")
        self.peak_label = self._make_stat(summary, "Peak")
        summary_card.add_widget(summary)
        form.add_widget(summary_card)

        form.add_widget(section_label("table", "Hourly Load Profile"))
        header_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.total_pct_label = MDLabel(
            text="Total: 100.00% (must equal 100%)", theme_text_color="Custom", text_color=TEXT_DARK,
        )
        header_row.add_widget(self.total_pct_label)
        reset_btn = tonal_button("RESET", on_release=self._reset_to_default, size_hint_x=None, width=dp(90))
        header_row.add_widget(reset_btn)
        form.add_widget(header_row)

        # Daytime (first 12 hours) and nighttime (last 12) sit side by side instead of one
        # 24-row column -- halves the scroll length and mirrors the day/night grouping
        # used everywhere else in the app (colors, ratio split, etc). No inner ScrollView:
        # the table is just part of the page's own scroll content, so there's one scroll
        # gesture and one scrollbar for the whole screen instead of a nested one.
        columns = MDBoxLayout(spacing=dp(8), size_hint_y=None)
        columns.bind(minimum_height=columns.setter("height"))
        day_col = self._build_hour_column("Daytime (6AM-5PM)", range(0, 12))
        night_col = self._build_hour_column("Nighttime (6PM-5AM)", range(12, 24))
        columns.add_widget(day_col)
        columns.add_widget(night_col)
        form.add_widget(columns)

        form.add_widget(section_label("chart-bar", "Hourly Load Chart"))
        legend = MDBoxLayout(spacing=dp(16), size_hint_y=None, height=dp(20))
        legend.add_widget(self._legend_entry("Daytime", ACCENT))
        legend.add_widget(self._legend_entry("Nighttime", ON_SURFACE_VARIANT))
        legend.add_widget(MDBoxLayout())
        form.add_widget(legend)
        self.chart = BarChart(size_hint_y=None, height=dp(180))
        form.add_widget(self.chart)

        form.add_widget(nav_row(self._go_back, "Next: Solar Sizing", self._go_next))

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _build_hour_column(self, title: str, indices: range) -> MDBoxLayout:
        col = MDBoxLayout(orientation="vertical", size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        # Solid green group-header bar spanning the Hour/%/kWh sub-columns below it,
        # echoing the reference table's grouped header row (e.g. "Fixed" over "<1y/>1y").
        col.add_widget(framed_label(title, dp(26), bold=True, bg=ACCENT, fg=WHITE))

        # 56dp: MDTextField's comfortable natural height (it reserves room for its
        # hint-label/underline chrome) -- the row was previously squeezed to 36-40dp,
        # which is what left the value looking cramped/off-center against its
        # neighboring cells. Taller rows, but a field that renders correctly beats a
        # compact one that doesn't.
        row_h = dp(56)
        grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(1), padding=dp(1),
                           row_default_height=row_h, row_force_default=True)
        grid.bind(minimum_height=grid.setter("height"))

        grid.add_widget(framed_label("Hour", row_h, bold=True, bg=HEADER_BG, full_border=True))
        grid.add_widget(framed_label("%", row_h, bold=True, bg=HEADER_BG, full_border=True))
        grid.add_widget(framed_label("kWh", row_h, bold=True, bg=HEADER_BG, full_border=True))
        for i in indices:
            # Hour column: light green. %/kWh columns: near-white (~10% green tint) --
            # each cell owns an explicit opaque background, nothing relies on bleed-through.
            # full_border=True on every cell (not just this table's header row) so the
            # whole thing reads as one bordered grid, <table>/<td>-style, rather than a
            # plain list of rows -- makes the boundary of the editable % cells obvious
            # against their read-only neighbors too.
            grid.add_widget(framed_label(HOUR_LABELS[i], row_h, bg=ACCENT_LIGHT, full_border=True))
            cell, pct_field = self._pct_cell(i, row_h)
            grid.add_widget(cell)
            self._pct_fields.append(pct_field)
            kwh_label = framed_label("0.00", row_h, bg=NEAR_WHITE, full_border=True)
            grid.add_widget(kwh_label)
            self._kwh_labels.append(kwh_label)
        col.add_widget(grid)
        return col

    def _pct_cell(self, index: int, height) -> tuple:
        # KivyMD's own fill/border chrome is switched off entirely (transparent fill,
        # transparent line in every state) -- the cell's background and border are
        # instead drawn by hand, at the exact same size as the field itself, in the
        # same style as the Hour/kWh framed_label cells either side of it (plain
        # white fill, thin ROW_LINE box, sized to the cell -- not the field's own
        # rounded/inset chrome). That keeps the % column reading as an ordinary
        # bordered table cell instead of a separate pill-shaped input floating
        # inside one. _PctField still overrides "fill" mode's hardcoded top-heavy
        # padding so the (invisible) fill/text stay vertically centered.
        field = _PctField(
            text=f"{self.hourly_pct[index]:.2f}", input_filter="float",
            font_size="13sp", size_hint=(1, None), height=height, halign="center",
            mode="fill", radius=[0, 0, 0, 0],
            fill_color_normal=(0, 0, 0, 0), fill_color_focus=(0, 0, 0, 0),
            text_color_normal=TEXT_DARK, text_color_focus=TEXT_DARK,
            line_color_normal=(0, 0, 0, 0), line_color_focus=(0, 0, 0, 0),
        )
        with field.canvas.before:
            Color(*WHITE)
            bg_rect = Rectangle(pos=field.pos, size=field.size)
            border_color = Color(*ROW_LINE)
            border = Line(rectangle=(0, 0, 0, 0), width=1)

        def _sync_border(instance, _value):
            bg_rect.pos = instance.pos
            bg_rect.size = instance.size
            border.rectangle = (instance.x, instance.y, instance.width, instance.height)
            border_color.rgba = ACCENT if instance.focus else ROW_LINE

        field.bind(pos=_sync_border, size=_sync_border, focus=_sync_border)
        field.bind(text=lambda _inst, val, idx=index: self._on_pct_changed(idx, val))
        return field, field

    def _legend_entry(self, label: str, color: tuple) -> MDBoxLayout:
        entry = MDBoxLayout(spacing=dp(6), size_hint=(None, None), size=(dp(90), dp(20)))
        swatch = Widget(size_hint=(None, None), size=(dp(12), dp(12)))
        with swatch.canvas:
            Color(*color)
            rect = Rectangle(pos=swatch.pos, size=swatch.size)
        swatch.bind(pos=lambda inst, val: setattr(rect, "pos", val))
        swatch_cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(12))
        swatch_cell.add_widget(swatch)
        entry.add_widget(swatch_cell)
        entry.add_widget(MDLabel(text=label, font_style="Caption", theme_text_color="Custom", text_color=TEXT_DARK))
        return entry

    def _make_stat(self, row: MDBoxLayout, title: str) -> MDLabel:
        box = MDBoxLayout(orientation="vertical")
        box.add_widget(stat_title_label(title))
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

    def _refresh_table(self, *_args) -> None:
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

        colors = [ACCENT if i < 12 else ON_SURFACE_VARIANT for i in range(len(hourly_kwh))]
        self.chart.set_data(hourly_kwh, HOUR_LABELS, colors)

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

    def collect_state(self) -> dict:
        """The raw, user-editable % table, for full-quote save/restore -- distinct
        from get_report_data()'s derived kWh figures, which the exported report
        needs but which aren't enough on their own to reconstruct this table."""
        return {"hourly_pct": list(self.hourly_pct)}

    def apply_state(self, data: dict) -> None:
        app = MDApp.get_running_app()
        self.daytime_pct = app.state.project.daytime_ratio_pct
        self.hourly_pct = list(data.get("hourly_pct") or default_hourly_percentages(self.daytime_pct))
        self._refresh_table()
        self._refresh_kwh_column()
        self._refresh_summary()

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

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "solar"
