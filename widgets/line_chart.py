"""Hand-drawn line chart -- no matplotlib, which doesn't package reliably for
Android. Supports several colored series (optionally dashed, with point markers),
an optional zero-crossing area fill (green above/red below) for one series, an
optional dashed vertical marker line with a label (e.g. a payback-year mark), and
an optional dashed horizontal marker line with a label (e.g. a battery's Depth of
Discharge floor). Y-axis reference values are shown on both the left and right
edges. Redraws whenever the widget is resized or set_data() is called again.
"""

from math import ceil

from kivy.graphics import Color, Ellipse, Line, Mesh
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.label import Label
from kivy.uix.widget import Widget

AXIS_COLOR = (0.35, 0.35, 0.35, 1)
GRID_COLOR = (0.82, 0.82, 0.82, 1)
ZERO_LINE_COLOR = (0.40, 0.40, 0.40, 1)
FILL_POS_COLOR = (0.18, 0.65, 0.32, 0.22)
FILL_NEG_COLOR = (0.80, 0.20, 0.20, 0.22)
TICK_EVERY = 3
MARKER_RADIUS = dp(2.6)


def _y_reference_values(y_min: float, y_max: float, count: int = 4) -> list[float]:
    """`count` evenly-spaced reference values for the y-axis (min, max, and
    count-2 points between them), preferring whole numbers. If the series barely
    moves, rounding every point to the nearest whole number can collide (several
    points landing on the same integer) -- when that happens, fall back to the
    raw evenly-divided points instead, so the axis still shows `count` distinct
    values rather than repeating the same number."""
    if y_max == y_min:
        return [y_min] * count
    raw = [y_min + i * (y_max - y_min) / (count - 1) for i in range(count)]
    rounded = [round(v) for v in raw]
    if len(set(rounded)) == count:
        return [float(v) for v in rounded]
    return raw


class LineChart(Widget):
    text_scale = NumericProperty(1)
    LEFT_MARGIN = dp(36)
    RIGHT_MARGIN = dp(34)
    TOP_MARGIN = dp(20)
    BOTTOM_MARGIN = dp(24)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._series: list[tuple] = []  # (values, color, dashed)
        self._x_labels: list[str] = []
        self._vline: dict | None = None
        self._hline: dict | None = None
        self._fill_index: int | None = None
        self._tick_labels: list[Label] = []
        self._legend = []
        self._x_unit = ""
        self._y_unit = ""
        self.bind(pos=self._redraw, size=self._redraw)

    def set_data(self, series: list[tuple], x_labels: list[str],
                 vline: dict | None = None, fill_index: int | None = None,
                 hline: dict | None = None, legend: list | None = None,
                 x_unit: str = "", y_unit: str = "") -> None:
        """series: list of (values, color) or (values, color, dashed_bool).
        vline: {"x": float_index, "label": str, "color": (r,g,b,a)} for a dashed vertical marker line.
        hline: {"y": float, "label": str, "color": (r,g,b,a)} for a dashed horizontal marker line
               (e.g. a battery's Depth of Discharge floor).
        fill_index: index into series to area-fill against y=0 (green above, red below)."""
        self._series = [s if len(s) == 3 else (s[0], s[1], False) for s in series]
        self._x_labels = x_labels
        self._vline = vline
        self._hline = hline
        self._fill_index = fill_index
        self._legend = list(legend or [])
        self._x_unit, self._y_unit = x_unit, y_unit
        self._redraw()

    def _clear_ticks(self) -> None:
        for lbl in self._tick_labels:
            self.remove_widget(lbl)
        self._tick_labels = []

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        self._clear_ticks()
        if not self._series or self.width <= 1 or self.height <= 1:
            return

        scale = self.text_scale
        # PHP cash-flow ticks can be seven digits wide (plus separators).
        # Reserve enough space on both sides when exporting the chart.
        axis_margin = dp(62) if self._y_unit == "PHP" else None
        x0 = self.x + (axis_margin or self.LEFT_MARGIN) * scale
        x1 = self.x + self.width - (axis_margin or self.RIGHT_MARGIN) * scale
        y0 = self.y + (dp(42) if self._x_unit else self.BOTTOM_MARGIN) * scale
        legend_rows = 2 if len(self._legend) > 2 else 1
        y1 = self.y + self.height - ((dp(35) + dp(25) * legend_rows) if self._legend else self.TOP_MARGIN) * scale
        plot_w = max(1.0, x1 - x0)
        plot_h = max(1.0, y1 - y0)
        n = len(self._x_labels)

        all_vals = [v for values, _c, _d in self._series for v in values] or [0.0]
        if self._hline is not None:
            all_vals = all_vals + [self._hline["y"]]
        y_min = min(0.0, min(all_vals))
        y_max = max(all_vals) if max(all_vals) > 0 else 1.0
        span = (y_max - y_min) or 1.0
        pad = span * 0.12
        y_min -= pad
        y_max += pad
        span = y_max - y_min

        def px(i: float, v: float) -> tuple[float, float]:
            fx = x0 + (i / (n - 1)) * plot_w if n > 1 else x0
            fy = y0 + ((v - y_min) / span) * plot_h
            return fx, fy

        y_zero = px(0, 0.0)[1]

        with self.canvas:
            Color(*GRID_COLOR)
            for g in range(5):
                gy = y0 + g / 4 * plot_h
                Line(points=[x0, gy, x1, gy], width=1)

            Color(*AXIS_COLOR)
            Line(points=[x0, y0, x1, y0], width=1.2)
            Line(points=[x0, y0, x0, y1], width=1.2)

            # Emphasized zero line -- distinct from the plot's bottom edge whenever
            # data dips negative (e.g. ROI's initial investment, or Grid buying).
            Color(*ZERO_LINE_COLOR)
            Line(points=[x0, y_zero, x1, y_zero], width=1.6)

            if self._fill_index is not None and 0 <= self._fill_index < len(self._series):
                values = self._series[self._fill_index][0]
                pts = [px(i, v) for i, v in enumerate(values)]
                self._draw_area_fill(pts, y_zero)

            for values, color, dashed in self._series:
                Color(*color)
                pts = []
                for i, v in enumerate(values):
                    fx, fy = px(i, v)
                    pts.extend([fx, fy])
                if dashed:
                    Line(points=pts, width=1.6, dash_length=7, dash_offset=4)
                else:
                    Line(points=pts, width=1.8)
                    for i, v in enumerate(values):
                        fx, fy = px(i, v)
                        Ellipse(pos=(fx - MARKER_RADIUS, fy - MARKER_RADIUS),
                                size=(MARKER_RADIUS * 2, MARKER_RADIUS * 2))

            if self._vline is not None:
                vx = px(self._vline["x"], 0)[0]
                Color(*self._vline.get("color", (0.4, 0.25, 0.6, 1)))
                Line(points=[vx, y0, vx, y1], width=1.4, dash_length=6, dash_offset=4)

            if self._hline is not None:
                hy = px(0, self._hline["y"])[1]
                Color(*self._hline.get("color", (0.4, 0.25, 0.6, 1)))
                Line(points=[x0, hy, x1, hy], width=2.4, dash_length=10, dash_offset=6)

        for value in _y_reference_values(y_min + pad, y_max - pad):
            text = f"{value:,.0f}" if value == round(value) else f"{value:.3g}"
            ref_y = px(0, value)[1]
            for side in ("left", "right"):
                self._add_y_label(text, x0 if side == "left" else x1, ref_y, side=side)

        if self._vline is not None:
            vx = px(self._vline["x"], 0)[0]
            lbl = Label(
                text=self._vline.get("label", ""), font_size=dp(9) * scale,
                color=self._vline.get("color", (0.4, 0.25, 0.6, 1)),
                size_hint=(None, None), size=(dp(120) * scale, dp(14) * scale),
                pos=(min(vx - dp(10), x1 - dp(120) * scale), y1 + dp(3)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

        if self._hline is not None:
            hy = px(0, self._hline["y"])[1]
            lbl = Label(
                text=self._hline.get("label", ""), font_size=dp(9) * scale, bold=True,
                color=self._hline.get("color", (0.4, 0.25, 0.6, 1)),
                size_hint=(None, None), size=(dp(90) * scale, dp(14) * scale), halign="left",
                pos=(x0 + dp(4), hy + dp(3)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

        tick_spacing = (dp(30) + dp(4)) * scale
        tick_every = max(TICK_EVERY, ceil((n - 1) * tick_spacing / plot_w)) if n > 1 else 1
        for i, label in enumerate(self._x_labels):
            if i != n - 1 and i % tick_every != 0:
                continue
            # Keep the final year/hour visible without placing it on top of
            # the preceding regular tick on narrow charts.
            if 0 < i < n - 1 and (n - 1 - i) * plot_w / (n - 1) < tick_spacing:
                continue
            fx, _fy = px(i, 0)
            lbl = Label(
                text=label, font_size=dp(9) * scale, color=(0.3, 0.3, 0.3, 1),
                size_hint=(None, None), size=(dp(30) * scale, dp(14) * scale),
                pos=(fx - dp(15) * scale, y0 - dp(20) * scale),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

        if self._legend:
            columns = min(2, len(self._legend))
            width = max(1, (x1 - x0) / columns)
            for index, label in enumerate(self._legend):
                color = self._series[index][1] if index < len(self._series) else AXIS_COLOR
                text = ("-- " if index < len(self._series) and self._series[index][2] else "- ") + label
                lbl = Label(text=text, font_size=dp(10) * scale, color=color,
                            size_hint=(None, None), size=(width, dp(26) * scale),
                            text_size=(width - dp(8) * scale, dp(26) * scale),
                            halign="left", valign="middle",
                            pos=(x0 + index % columns * width,
                                 self.top - dp(28 + 25 * (index // columns)) * scale))
                self.add_widget(lbl)
                self._tick_labels.append(lbl)
        for text, pos, size in ((self._x_unit, ((x0 + x1) / 2 - dp(40) * scale, self.y), (dp(80) * scale, dp(18) * scale)),
                                (self._y_unit, (self.x, y1 + dp(3) * scale), (dp(36) * scale, dp(16) * scale))):
            if text:
                lbl = Label(text=text, font_size=dp(10) * scale, color=AXIS_COLOR, size_hint=(None, None), size=size, pos=pos)
                self.add_widget(lbl)
                self._tick_labels.append(lbl)

    def _draw_area_fill(self, pts: list[tuple[float, float]], y_zero: float) -> None:
        """Fills the area between the curve and the zero line as solid triangles
        (a proper polygon fill), not the previous approach of packing many thin
        adjacent vertical Line strokes side by side to approximate a fill -- that
        produced a visibly jagged/hatched edge once exported to PNG at chart
        resolution. Split into same-signed runs (inserting an interpolated vertex
        exactly at each zero-crossing) so the green/red split stays exact."""
        dense_pts = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            if (a[1] - y_zero) * (b[1] - y_zero) < 0:
                t = (y_zero - a[1]) / (b[1] - a[1])
                dense_pts.append((a[0] + (b[0] - a[0]) * t, y_zero))
            dense_pts.append(b)

        runs: list[list[tuple[float, float]]] = []
        current = [dense_pts[0]]
        for p in dense_pts[1:]:
            current.append(p)
            if p[1] == y_zero:
                runs.append(current)
                current = [p]
        if len(current) > 1:
            runs.append(current)

        for run in runs:
            if len(run) < 2:
                continue
            avg_y = sum(p[1] for p in run) / len(run)
            vertices = []
            for x, y in run:
                vertices.extend([x, y_zero, 0, 0])
                vertices.extend([x, y, 0, 0])
            indices = []
            for i in range(len(run) - 1):
                base = 2 * i
                indices.extend([base, base + 1, base + 2, base + 1, base + 2, base + 3])
            Color(*(FILL_POS_COLOR if avg_y >= y_zero else FILL_NEG_COLOR))
            Mesh(vertices=vertices, indices=indices, mode="triangles")

    def _add_y_label(self, text: str, x: float, y: float, side: str = "left") -> None:
        """y is the exact pixel height the value maps to on the plot -- the label
        is vertically centered on it."""
        lbl = Label(
            text=text, font_size=dp(9) * self.text_scale, color=(0.3, 0.3, 0.3, 1),
            size_hint=(None, None), size=(dp(58 if self._y_unit == "PHP" else 32) * self.text_scale,
                                         dp(14) * self.text_scale),
            halign="right" if side == "left" else "left",
        )
        x_offset = (-dp(60 if self._y_unit == "PHP" else 34) if side == "left" else dp(2)) * self.text_scale
        lbl.pos = (x + x_offset, y - dp(7) * self.text_scale)
        self.add_widget(lbl)
        self._tick_labels.append(lbl)
