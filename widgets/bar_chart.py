"""Hand-drawn hourly bar chart -- same no-matplotlib approach as widgets/line_chart.py
(matplotlib doesn't package reliably for Android). Shows one bar per hour, colored by
day/night so it visually matches the Hourly Load Profile table above it on the
Consumption screen. Redraws whenever the widget is resized or set_data() is called.
"""

from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.widget import Widget

AXIS_COLOR = (0.35, 0.35, 0.35, 1)
GRID_COLOR = (0.88, 0.88, 0.85, 1)
TICK_EVERY = 3


class BarChart(Widget):
    LEFT_MARGIN = dp(36)
    RIGHT_MARGIN = dp(10)
    TOP_MARGIN = dp(10)
    BOTTOM_MARGIN = dp(24)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._values: list[float] = []
        self._labels: list[str] = []
        self._colors: list[tuple] = []
        self._tick_labels: list[Label] = []
        self.bind(pos=self._redraw, size=self._redraw)

    def set_data(self, values: list[float], labels: list[str], colors: list[tuple]) -> None:
        """values/labels/colors are parallel lists, one entry per bar."""
        self._values = values
        self._labels = labels
        self._colors = colors
        self._redraw()

    def _clear_ticks(self) -> None:
        for lbl in self._tick_labels:
            self.remove_widget(lbl)
        self._tick_labels = []

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        self._clear_ticks()
        if not self._values or self.width <= 1 or self.height <= 1:
            return

        x0 = self.x + self.LEFT_MARGIN
        x1 = self.x + self.width - self.RIGHT_MARGIN
        y0 = self.y + self.BOTTOM_MARGIN
        y1 = self.y + self.height - self.TOP_MARGIN
        plot_w = max(1.0, x1 - x0)
        plot_h = max(1.0, y1 - y0)
        n = len(self._values)

        y_max = max(self._values) if max(self._values) > 0 else 1.0
        y_max *= 1.15

        slot_w = plot_w / n
        bar_w = slot_w * 0.6

        with self.canvas:
            Color(*GRID_COLOR)
            for g in range(5):
                gy = y0 + g / 4 * plot_h
                Line(points=[x0, gy, x1, gy], width=1)

            Color(*AXIS_COLOR)
            Line(points=[x0, y0, x1, y0], width=1.2)
            Line(points=[x0, y0, x0, y1], width=1.2)

            for i, value in enumerate(self._values):
                bar_h = (value / y_max) * plot_h if y_max > 0 else 0.0
                bx = x0 + i * slot_w + (slot_w - bar_w) / 2
                Color(*self._colors[i])
                Rectangle(pos=(bx, y0), size=(bar_w, bar_h))

        self._add_y_label(f"{y_max:.1f}", x0, y1, top=True)
        self._add_y_label("0", x0, y0, top=False)

        for i, label in enumerate(self._labels):
            if i % TICK_EVERY != 0 and i != n - 1:
                continue
            fx = x0 + i * slot_w + slot_w / 2
            lbl = Label(
                text=label, font_size="9sp", color=(0.3, 0.3, 0.3, 1),
                size_hint=(None, None), size=(dp(30), dp(14)),
                pos=(fx - dp(15), y0 - dp(20)),
            )
            self.add_widget(lbl)
            self._tick_labels.append(lbl)

    def _add_y_label(self, text: str, x: float, y: float, top: bool) -> None:
        lbl = Label(
            text=text, font_size="9sp", color=(0.3, 0.3, 0.3, 1),
            size_hint=(None, None), size=(dp(32), dp(14)), halign="right",
        )
        lbl.pos = (x - dp(34), y + (-dp(4) if top else -dp(10)))
        self.add_widget(lbl)
        self._tick_labels.append(lbl)
