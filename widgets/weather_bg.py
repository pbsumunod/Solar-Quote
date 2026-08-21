"""A themed decorative background covering a whole screen area: a drawn vertical
gradient (approximating a warm sunburst / soft cloud layer / rain-on-glass photo --
photos pasted into chat aren't accessible as files, so this is a procedural
stand-in for the same mood) plus a weather icon/effect. The scenario can be
changed at runtime via set_scenario(). Rainy additionally animates falling
raindrop streaks via Clock, since "rain falls" implies motion."""

import random

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivymd.uix.label import MDIcon

# Each gradient is a list of (r, g, b) stops from top to bottom.
GRADIENTS = {
    "Sunny": [(1.0, 0.95, 0.75), (1.0, 0.80, 0.45), (0.98, 0.62, 0.40)],
    "Cloudy": [(0.92, 0.93, 0.95), (0.82, 0.83, 0.86), (0.72, 0.73, 0.76)],
    "Rainy": [(0.16, 0.30, 0.50), (0.28, 0.48, 0.68), (0.52, 0.70, 0.85)],
}
GRADIENT_ALPHA = 0.55
GRADIENT_STEPS = 36

RAINDROP_COUNT = 22
RAINDROP_COLOR = (0.85, 0.92, 1.0, 0.65)


def _interp(stops: list[tuple], t: float) -> tuple:
    n = len(stops) - 1
    if n <= 0:
        return stops[0]
    seg = min(int(t * n), n - 1)
    local_t = (t * n) - seg
    a, b = stops[seg], stops[seg + 1]
    return tuple(a[i] + (b[i] - a[i]) * local_t for i in range(3))


def rect_tint(scenario: str) -> tuple:
    """The mid-gradient color, used to tint data rectangles (fields/stat labels)
    so they visually belong to the same theme as the background."""
    stops = GRADIENTS.get(scenario, GRADIENTS["Sunny"])
    mid = stops[len(stops) // 2]
    return (mid[0], mid[1], mid[2], 0.55)


class WeatherBackground(FloatLayout):
    def __init__(self, scenario: str = "Sunny", **kwargs):
        super().__init__(**kwargs)
        self.scenario = scenario
        self._icons: list = []
        self._raindrops: list[list[float]] = []
        self._anim_ev = None
        self.bind(pos=self._redraw_gradient, size=self._redraw_gradient)
        self._redraw_gradient()
        self._apply_icons()
        if scenario == "Rainy":
            self._start_rain()

    def set_scenario(self, scenario: str) -> None:
        if scenario == self.scenario:
            return
        self.stop()
        self.scenario = scenario
        self._redraw_gradient()
        self._apply_icons()
        if scenario == "Rainy":
            self._start_rain()
        else:
            self.canvas.after.clear()

    def _redraw_gradient(self, *_args) -> None:
        self.canvas.before.clear()
        if self.width <= 1 or self.height <= 1:
            return
        stops = GRADIENTS[self.scenario]
        band_h = self.height / GRADIENT_STEPS
        with self.canvas.before:
            for i in range(GRADIENT_STEPS):
                t = i / (GRADIENT_STEPS - 1)
                r, g, b = _interp(stops, t)
                Color(r, g, b, GRADIENT_ALPHA)
                Rectangle(pos=(self.x, self.y + self.height - (i + 1) * band_h), size=(self.width, band_h + 1))

            if self.scenario == "Sunny":
                cx, cy = self.x + self.width * 0.75, self.y + self.height * 0.95
                for scale, alpha in [(1.0, 0.18), (0.6, 0.30), (0.3, 0.45)]:
                    rr = min(self.width, self.height) * 0.5 * scale
                    Color(1, 0.96, 0.75, alpha)
                    Ellipse(pos=(cx - rr / 2, cy - rr / 2), size=(rr, rr))

    def _apply_icons(self) -> None:
        for icon in self._icons:
            self.remove_widget(icon)
        self._icons = []
        if self.scenario == "Cloudy":
            for px, py, size in [(0.18, 0.96, 36), (0.5, 0.99, 46), (0.82, 0.95, 36)]:
                icon = MDIcon(
                    icon="weather-cloudy", theme_text_color="Custom", text_color=(1, 1, 1, 0.8),
                    font_size=f"{size}sp", pos_hint={"center_x": px, "center_y": py},
                    size_hint=(None, None), size=(dp(size), dp(size)),
                )
                self.add_widget(icon)
                self._icons.append(icon)

    def _start_rain(self) -> None:
        self._raindrops = [[random.random(), random.random(), random.uniform(0.6, 1.3)] for _ in range(RAINDROP_COUNT)]
        self._anim_ev = Clock.schedule_interval(self._animate_rain, 1 / 15)

    def _animate_rain(self, _dt) -> None:
        self.canvas.after.clear()
        if self.width <= 1 or self.height <= 1:
            return
        with self.canvas.after:
            Color(*RAINDROP_COLOR)
            for drop in self._raindrops:
                drop[1] -= 0.03 * drop[2]
                if drop[1] < 0:
                    drop[1] = 1.0
                    drop[0] = random.random()
                x = self.x + drop[0] * self.width
                y = self.y + drop[1] * self.height
                Line(points=[x, y, x - dp(2), y - dp(14)], width=1.6)

    def stop(self) -> None:
        if self._anim_ev:
            self._anim_ev.cancel()
            self._anim_ev = None

    def start(self) -> None:
        if self.scenario == "Rainy" and self._anim_ev is None:
            self._start_rain()
