"""Hand-drawn line chart -- no matplotlib, which doesn't package reliably for
Android. Supports several colored series (optionally dashed, with point markers),
an optional zero-crossing area fill (green above/red below) for one series, an
optional dashed vertical marker line with a label (e.g. a payback-year mark), and
an optional dashed horizontal marker line with a label (e.g. a battery's Depth of
Discharge floor). Y-axis reference values are shown on both the left and right
edges. Redraws whenever the widget is resized or set_data() is called again.
"""

from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.widget import Widget

AXIS_COLOR = (0.35, 0.35, 0.35, 1)
GRID_COLOR = (0.82, 0.82, 0.82, 1)
ZERO_LINE_COLOR = (0.40, 0.40, 0.40, 1)
FILL_POS_COLOR = (0.18, 0.65, 0.32, 0.22)
FILL_NEG_COLOR = (0.80, 0.20, 0.20, 0.22)
TICK_EVERY = 3
MARKER_RADIUS = dp(2.6)


def _y_reference_values(y_min: float, y_max: float) -> tuple[float, float]:
    """At least 2 distinct reference values for the y-axis, preferring whole
    numbers. If y_min/y_max round to the same whole number (the series barely
    moves), whole numbers can't tell them apart -- fall back to two points
    evenly dividing the actual range instead, so the axis still shows something
    meaningful rather than the same number twice."""
    r_min, r_max = round(y_min), round(y_max)
    if r_max != r_min:
        return float(r_min), float(r_max)
    if y_max == y_min:
        return y_min, y_max
    third = (y_max - y_min) / 3
    return y_min + third, y_min + 2 * third


class LineChart(Widget):
    LEFT_MARGIN = dp(36)
    RIGHT_MARGIN = dp(34)
    TOP_MARGIN = dp(6)
    BOTTOM_MARGIN = dp(24)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._series: list[tuple] = []  # (values, color, dashed)
        self._x_labels: list[str] = []
        self._vline: dict | None = None
        self._hline: dict | None = None
        self._fill_index: int | None = None
        self._tick_labels: list[Label] = []
        self.bind(pos=self._redraw, size=self._redraw)

    def set_data(self, series: list[tuple], x_labels: list[str],
                 vline: dict | None = None, fill_index: int | None = None,
                 hline: dict | None = None) -> None:
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

        x0 = self.x + self.LEFT_MARGIN
        x1 = self.x + self.width - self.RIGHT_MARGIN
        y0 = self.y + self.BOTTOM_MARGIN
        y1 = self.y + self.height - self.TOP_MARGIN
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
                substeps = 6
                for a, b in zip(pts, pts[1:]):
                    for s in range(substeps):
                        t0, t1 = s / substeps, (s + 1) / substeps
                        xa, ya = a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0
                        xb, yb = a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1
                        xm, ym = (xa + xb) / 2, (ya + yb) / 2
                        Color(*(FILL_POS_COLOR if ym >= y_zero else FILL_NEG_COLOR))
                        Line(points=[xm, y_zero, xm, ym], width=(xb - xa) + 1)

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

        ref_lo, ref_hi = _y_reference_values(y_min + pad, y_max - pad)
        for side in ("left", "right"):
            self._add_y_label(f"{ref_hi:.0f}" if ref_hi == round(ref_hi) else f"{ref_hi:.1f}",
                               x0 if side == "left" else x1, y1, top=True, side=side)
            self._add_y_label(f"{ref_lo:.0f}" if ref_lo == round(ref_lo) else f"{ref_lo:.1f}",
                               x0 if side == "left" else x1, y0, top=False, side=side)

        if self._vline is not None:
            vx = px(self._vline["x"], 0)[0]
            lbl = Label(
                text=self._vline.get("label", ""), font_size="9sp",
                color=self._vline.get("color", (0.4, 0.25, 0.6, 1)),
                size_hint=(None, None), size=(dp(70), dp(14)),
                pos=(vx - dp(5), y1 - dp(2)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

        if self._hline is not None:
            hy = px(0, self._hline["y"])[1]
            lbl = Label(
                text=self._hline.get("label", ""), font_size="9sp", bold=True,
                color=self._hline.get("color", (0.4, 0.25, 0.6, 1)),
                size_hint=(None, None), size=(dp(90), dp(14)), halign="left",
                pos=(x0 + dp(4), hy + dp(3)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

        for i, label in enumerate(self._x_labels):
            if i % TICK_EVERY != 0 and i != n - 1:
                continue
            fx, _fy = px(i, 0)
            lbl = Label(
                text=label, font_size="9sp", color=(0.3, 0.3, 0.3, 1),
                size_hint=(None, None), size=(dp(30), dp(14)),
                pos=(fx - dp(15), y0 - dp(20)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

    def _add_y_label(self, text: str, x: float, y: float, top: bool, side: str = "left") -> None:
        lbl = Label(
            text=text, font_size="9sp", color=(0.3, 0.3, 0.3, 1),
            size_hint=(None, None), size=(dp(32), dp(14)),
            halign="right" if side == "left" else "left",
        )
        x_offset = -dp(34) if side == "left" else dp(2)
        lbl.pos = (x + x_offset, y + (-dp(4) if top else -dp(10)))
        self.add_widget(lbl)
        self._tick_labels.append(lbl)
