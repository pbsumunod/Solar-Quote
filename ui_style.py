"""Shared color constants and small helpers so buttons/tables read clearly on a white background."""

from kivy.metrics import dp
from kivy.graphics import Color, Line, Rectangle
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

ACCENT = (0.180, 0.494, 0.204, 1)    # Material Green 700, the app's brand color
ACCENT_LIGHT = (0.788, 0.902, 0.788, 1)  # light green tint, for sub-column header cells and the Hour column
TEXT_DARK = (0.08, 0.08, 0.08, 1)    # near-black, for table/body text
WHITE = (1, 1, 1, 1)
CELL_BG = (1, 1, 1, 1)               # data cell background
HEADER_BG = ACCENT_LIGHT              # light green, for table sub-column header row
NEAR_WHITE = (0.95, 0.98, 0.95, 1)    # ~10% green tint, for the %/kWh data columns
LIGHT_GREEN_BG = ACCENT_LIGHT         # same shade as the Consumption table's Hour column, for result/editable fields app-wide
ROW_LINE = (0.80, 0.82, 0.80, 1)      # thin bottom border drawn per cell -- row divider
OK_GREEN = (0.118, 0.490, 0.133, 1)
BAD_RED = (0.776, 0.157, 0.157, 1)
WARN_OK_BG = (0.85, 0.95, 0.85, 1)
WARN_BAD_BG = (0.99, 0.87, 0.87, 1)


def framed_label(text: str, height, bold: bool = False, bg=CELL_BG, fg=TEXT_DARK) -> MDLabel:
    """An MDLabel with an explicit opaque background, dark text, and a thin bottom border,
    so it reads clearly and rows stay visually separated without relying on a parent
    background showing through layout spacing (which doesn't reliably clip to content)."""
    lbl = MDLabel(
        text=text, bold=bold, font_style="Caption", halign="center",
        size_hint_y=None, height=height,
        theme_text_color="Custom", text_color=fg,
    )
    with lbl.canvas.before:
        Color(*bg)
        rect = Rectangle(pos=lbl.pos, size=lbl.size)
        Color(*ROW_LINE)
        border = Line(points=[], width=1)

    def _sync(instance, _value):
        rect.pos = instance.pos
        rect.size = instance.size
        x, y = instance.pos
        w, _h = instance.size
        border.points = [x, y, x + w, y]

    lbl.bind(pos=_sync, size=_sync)
    return lbl


def green_field(**kwargs) -> MDTextField:
    """An MDTextField with the app-wide light-green 'editable data' background
    (same shade as the Consumption table's Hour column)."""
    kwargs.setdefault("mode", "fill")
    kwargs.setdefault("fill_color_normal", LIGHT_GREEN_BG)
    kwargs.setdefault("fill_color_focus", WHITE)
    return MDTextField(**kwargs)


def with_bg(widget, bg=LIGHT_GREEN_BG):
    """Draws an opaque background rectangle behind any widget (e.g. a result MDLabel)
    without altering its other properties. The Color instruction is exposed as
    widget.bg_color so callers can re-tint it later (widget.bg_color.rgba = ...)."""
    with widget.canvas.before:
        color = Color(*bg)
        rect = Rectangle(pos=widget.pos, size=widget.size)

    def _sync(instance, _value):
        rect.pos = instance.pos
        rect.size = instance.size

    widget.bind(pos=_sync, size=_sync)
    widget.bg_color = color
    return widget


def warning_row(ok: bool, text: str) -> MDBoxLayout:
    """A single engineering-warning line: a check/close icon, wrapped text, a light
    green/red background depending on ok, and a white bottom divider between rows."""
    bg = WARN_OK_BG if ok else WARN_BAD_BG
    icon_color = OK_GREEN if ok else BAD_RED

    row = MDBoxLayout(orientation="horizontal", spacing=dp(8), padding=dp(8), size_hint_y=None)
    icon = MDIcon(
        icon="check-circle" if ok else "close-circle",
        theme_text_color="Custom", text_color=icon_color,
        size_hint=(None, None), size=(dp(24), dp(24)), pos_hint={"top": 1},
    )
    label = MDLabel(text=text, theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None)
    label.bind(texture_size=lambda _i, val: setattr(label, "height", val[1]))
    label.bind(width=lambda _i, val: setattr(label, "text_size", (val, None)))
    row.add_widget(icon)
    row.add_widget(label)
    row.bind(minimum_height=row.setter("height"))

    with row.canvas.before:
        Color(*bg)
        rect = Rectangle(pos=row.pos, size=row.size)
        Color(*WHITE)
        border = Line(points=[], width=1.5)

    def _sync(instance, _value):
        rect.pos = instance.pos
        rect.size = instance.size
        x, y = instance.pos
        w, _h = instance.size
        border.points = [x, y, x + w, y]

    row.bind(pos=_sync, size=_sync)
    return row


def top_app_bar(title: str, on_back=None) -> MDTopAppBar:
    """Solid-green header bar with a white title, matching the reference app-bar style.
    Pass on_back to show a back arrow (omitted on the root/first screen)."""
    left_items = [["arrow-left", lambda *_a: on_back()]] if on_back else []
    return MDTopAppBar(
        title=title, left_action_items=left_items,
        md_bg_color=ACCENT, specific_text_color=WHITE, elevation=2,
    )
