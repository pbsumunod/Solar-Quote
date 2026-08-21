"""A small drawn line+dot legend swatch, matching a chart series' style (solid or
dashed). Deliberately not a text glyph (e.g. a bullet character) -- those depend on
the device's active font having that character, and one user saw an unsupported
one render as a fallback box/"X" on their phone. Drawing it directly with
kivy.graphics guarantees it always renders the same way."""

from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.uix.widget import Widget


class LegendSwatch(Widget):
    def __init__(self, color: tuple, dashed: bool = False, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(26), dp(14)))
        super().__init__(**kwargs)
        self.color = color
        self.dashed = dashed
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if self.width <= 1 or self.height <= 1:
            return
        cy = self.y + self.height / 2
        with self.canvas:
            Color(*self.color)
            if self.dashed:
                Line(points=[self.x, cy, self.x + self.width, cy], width=1.8, dash_length=5, dash_offset=3)
            else:
                Line(points=[self.x, cy, self.x + self.width, cy], width=1.8)
                r = dp(2.6)
                Ellipse(pos=(self.x + self.width / 2 - r, cy - r), size=(r * 2, r * 2))
