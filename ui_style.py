"""Shared Material 3 color tokens and reusable components used across all screens.

Palette is grounded in the app's original brand green (ACCENT/ACCENT_LIGHT below,
unchanged from the pre-redesign values) plus a small set of neutral M3 surface/
outline tokens layered on top, so the accent is used for emphasis rather than
painted on every interactive element. See the "SolarQuote Client Screen" design
mockup for the reference layout this module implements in Kivy.
"""

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFillRoundFlatButton, MDFillRoundFlatIconButton, MDIconButton, MDRoundFlatButton
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.textfield import MDTextField

# --- Brand tokens (unchanged from the pre-redesign palette) --------------------
ACCENT = (0.180, 0.494, 0.204, 1)        # #2E7E34, Material Green 700-ish -- the brand color
ACCENT_LIGHT = (0.788, 0.902, 0.788, 1)  # #C9E6C9, light green tint
TEXT_DARK = (0.08, 0.08, 0.08, 1)
WHITE = (1, 1, 1, 1)
CELL_BG = (1, 1, 1, 1)
HEADER_BG = ACCENT_LIGHT
NEAR_WHITE = (0.95, 0.98, 0.95, 1)
LIGHT_GREEN_BG = ACCENT_LIGHT
ROW_LINE = (0.80, 0.82, 0.80, 1)
OK_GREEN = (0.118, 0.490, 0.133, 1)
BAD_RED = (0.776, 0.157, 0.157, 1)
WARN_OK_BG = (0.85, 0.95, 0.85, 1)
WARN_BAD_BG = (0.99, 0.87, 0.87, 1)

# --- M3 neutral surface/outline tokens ------------------------------------------
SURFACE = (0.992, 0.988, 0.973, 1)            # #FDFCF8, warm near-white page background
SURFACE_CONTAINER = (0.953, 0.945, 0.918, 1)  # #F3F1EA, section card / tonal row background
OUTLINE = (0.788, 0.777, 0.737, 1)            # #C9C6BC, field border
OUTLINE_VARIANT = (0.886, 0.875, 0.827, 1)    # #E2DFD3, hairline divider
ON_SURFACE = (0.110, 0.110, 0.094, 1)         # #1C1C18, primary text
ON_SURFACE_VARIANT = (0.282, 0.278, 0.243, 1) # #48473E, secondary/caption text and icons
ON_PRIMARY_CONTAINER = (0.078, 0.200, 0.094, 1)  # #143318, text/icon on ACCENT_LIGHT

LOGO_PATH = "assets/images/logo.png"
APP_VERSION = "0.1.0"  # keep in sync with buildozer.spec's version
# Bumped by hand on each delivered build -- shown on the Report and About screens
# so a build can be confirmed at a glance instead of guessed from behavior alone.
BUILD_LABEL = "2026-08-21-k"

STEP_NAMES = [
    "Client Info", "Consumption", "Solar Sizing", "Battery Sizing",
    "System Design", "Simulation", "Savings & ROI", "Report",
]


# --- Table/warning helpers (unchanged) ------------------------------------------

def framed_label(text: str, height, bold: bool = False, bg=CELL_BG, fg=TEXT_DARK,
                  full_border: bool = False) -> MDLabel:
    """An MDLabel with an explicit opaque background, dark text, and a thin border,
    so it reads clearly and rows stay visually separated without relying on a parent
    background showing through layout spacing (which doesn't reliably clip to content).
    full_border=False (the default, unchanged from before) draws only a bottom rule,
    the plain row-separator look most tables use; full_border=True draws a complete
    box on all four sides, for a table that should read as a proper <table>/<td> grid
    (e.g. Consumption's Hourly Load Profile) rather than a list of rows."""
    lbl = MDLabel(
        text=text, bold=bold, font_style="Caption", halign="center",
        size_hint_y=None, height=height,
        theme_text_color="Custom", text_color=fg,
    )
    with lbl.canvas.before:
        Color(*bg)
        rect = Rectangle(pos=lbl.pos, size=lbl.size)
        Color(*ROW_LINE)
        border = Line(rectangle=(0, 0, 0, 0), width=1) if full_border else Line(points=[], width=1)

    def _sync(instance, _value):
        rect.pos = instance.pos
        rect.size = instance.size
        x, y = instance.pos
        w, h = instance.size
        if full_border:
            border.rectangle = (x, y, w, h)
        else:
            border.points = [x, y, x + w, y]

    lbl.bind(pos=_sync, size=_sync)
    return lbl


def with_bg(widget, bg=LIGHT_GREEN_BG) -> object:
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
        size_hint=(None, None), size=(dp(24), dp(24)),
    )
    icon_cell = AnchorLayout(anchor_x="center", anchor_y="top", size_hint=(None, 1), width=dp(24))
    icon_cell.add_widget(icon)
    label = MDLabel(text=text, theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None)
    label.bind(texture_size=lambda _i, val: setattr(label, "height", val[1]))
    label.bind(width=lambda _i, val: setattr(label, "text_size", (val, None)))
    row.add_widget(icon_cell)
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


def _icon_cell(icon: str, color=None, size=20, width=24) -> AnchorLayout:
    """A small icon deterministically centered in a fixed-width, row-height-filling
    cell -- for icons placed directly in a horizontal row (PickerField, project_row,
    section_label), as opposed to _centered() which wraps a self-sizing button."""
    cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(width))
    cell.add_widget(MDIcon(
        icon=icon, theme_text_color="Custom", text_color=color or ON_SURFACE_VARIANT,
        size_hint=(None, None), size=(dp(size), dp(size)),
    ))
    return cell


def _centered(widget, width) -> AnchorLayout:
    """Wraps a widget that manages its own fixed size (MDIconButton, MDFillRoundFlat
    IconButton, Image) in an AnchorLayout so it's reliably centered on the cross-axis
    of a horizontal BoxLayout row. BoxLayout does NOT center children on the
    perpendicular axis -- it bottom/left-anchors them -- so anything whose natural
    height differs from the row's padded content height (e.g. MDIconButton always
    sets its own ~48dp height regardless of size_hint_y) visibly drifts off-center
    against Label siblings, which stretch to fill the row and self-center their text.

    `width` seeds the cell so there's no zero-width flash; buttons that compute their
    own final width a frame later (MDIconButton, MDFillRoundFlatIconButton) then keep
    the cell in sync via this binding rather than clipping at the seeded estimate."""
    cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=width)
    widget.bind(width=lambda _i, val: setattr(cell, "width", max(val, width)))
    cell.add_widget(widget)
    return cell


# --- M3 page header: top bar + step progress ------------------------------------

def screen_header(title: str, step: int | None, on_back=None, show_logo: bool = False, right_widget=None) -> MDBoxLayout:
    """Surface-toned top bar (back arrow or brand logo, screen title) plus an
    8-step progress track showing where this screen sits in the wizard flow.
    Pass step=None for utility screens outside the wizard (e.g. About) -- the
    progress track is omitted entirely rather than showing a meaningless step."""
    root = MDBoxLayout(orientation="vertical", size_hint_y=None)
    root.bind(minimum_height=root.setter("height"))

    bar = MDBoxLayout(
        orientation="horizontal", spacing=dp(12), padding=(dp(12), dp(10)),
        size_hint_y=None, height=dp(56),
    )
    with bar.canvas.before:
        Color(*SURFACE)
        bar_rect = Rectangle(pos=bar.pos, size=bar.size)
        Color(*OUTLINE_VARIANT)
        bar_border = Line(points=[], width=1)

    def _sync_bar(instance, _value):
        bar_rect.pos = instance.pos
        bar_rect.size = instance.size
        x, y = instance.pos
        w, _h = instance.size
        bar_border.points = [x, y, x + w, y]

    bar.bind(pos=_sync_bar, size=_sync_bar)

    if on_back:
        back_btn = MDIconButton(
            icon="arrow-left", theme_text_color="Custom", text_color=ON_SURFACE,
            on_release=lambda *_a: on_back(),
        )
        bar.add_widget(_centered(back_btn, width=dp(40)))
    elif show_logo:
        bar.add_widget(_centered(
            Image(source=LOGO_PATH, size_hint=(None, None), size=(dp(34), dp(34))),
            width=dp(40),
        ))
    else:
        bar.add_widget(Widget(size_hint=(None, None), size=(dp(8), dp(8))))

    title_label = MDLabel(
        text=title, bold=True, font_style="H6",
        theme_text_color="Custom", text_color=ON_SURFACE,
    )
    bar.add_widget(title_label)
    if right_widget is not None:
        bar.add_widget(_centered(right_widget, width=right_widget.width or dp(90)))
    root.add_widget(bar)

    if step is None:
        return root

    progress = MDBoxLayout(
        orientation="vertical", spacing=dp(6), padding=(dp(16), dp(8), dp(16), dp(10)),
        size_hint_y=None, height=dp(34),
    )
    with progress.canvas.before:
        Color(*SURFACE)
        progress_rect = Rectangle(pos=progress.pos, size=progress.size)
        Color(*OUTLINE_VARIANT)
        progress_border = Line(points=[], width=1)

    def _sync_progress(instance, _value):
        progress_rect.pos = instance.pos
        progress_rect.size = instance.size
        x, y = instance.pos
        w, _h = instance.size
        progress_border.points = [x, y, x + w, y]

    progress.bind(pos=_sync_progress, size=_sync_progress)

    step_label = MDLabel(
        text=f"Step {step} of {len(STEP_NAMES)} · {STEP_NAMES[step - 1]}",
        font_style="Caption", size_hint_y=None, height=dp(14),
        theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
    )
    progress.add_widget(step_label)

    track = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(4))
    for i in range(len(STEP_NAMES)):
        seg = Widget(size_hint_x=1)
        color = ACCENT if i < step else OUTLINE_VARIANT
        with seg.canvas:
            Color(*color)
            seg_rect = Rectangle(pos=seg.pos, size=seg.size)

        def _sync_seg(instance, _value, seg_rect=seg_rect):
            seg_rect.pos = instance.pos
            seg_rect.size = instance.size

        seg.bind(pos=_sync_seg, size=_sync_seg)
        track.add_widget(seg)
    progress.add_widget(track)
    root.add_widget(progress)

    return root


# --- M3 outlined text field -------------------------------------------------------

def m3_field(hint_text: str, icon: str | None = None, **kwargs) -> MDTextField:
    """An outlined, rounded Material 3-style text field with an optional leading icon."""
    kwargs.setdefault("mode", "rectangle")
    kwargs.setdefault("radius", [dp(14)] * 4)
    kwargs.setdefault("line_color_normal", OUTLINE)
    kwargs.setdefault("line_color_focus", ACCENT)
    kwargs.setdefault("hint_text_color_normal", ON_SURFACE_VARIANT)
    kwargs.setdefault("hint_text_color_focus", ACCENT)
    kwargs.setdefault("text_color_normal", ON_SURFACE)
    kwargs.setdefault("text_color_focus", ON_SURFACE)
    if icon:
        kwargs.setdefault("icon_left", icon)
        kwargs.setdefault("icon_left_color_normal", ON_SURFACE_VARIANT)
        kwargs.setdefault("icon_left_color_focus", ACCENT)
    return MDTextField(hint_text=hint_text, **kwargs)


# Back-compat alias for any leftover callers -- prefer m3_field() for new fields.
def green_field(**kwargs) -> MDTextField:
    hint_text = kwargs.pop("hint_text", "")
    return m3_field(hint_text, **kwargs)


class PickerField(ButtonBehavior, MDBoxLayout):
    """An outlined row styled like m3_field but tappable, for actions that open a
    dropdown menu or bottom sheet (country, ratio, scenario, maintenance method)
    instead of taking direct text input."""

    def __init__(self, icon: str, label: str, value: str = "", **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(52))
        kwargs.setdefault("padding", (dp(12), 0))
        kwargs.setdefault("spacing", dp(10))
        super().__init__(**kwargs)

        with self.canvas.before:
            Color(*OUTLINE)
            self._border = Line(rounded_rectangle=(0, 0, 0, 0, 14), width=1.2)
        self.bind(pos=self._sync, size=self._sync)

        self.add_widget(_icon_cell(icon))
        col = BoxLayout(orientation="vertical")
        self._label = MDLabel(
            text=label, font_style="Caption", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
        )
        self._value = MDLabel(text=value, theme_text_color="Custom", text_color=ON_SURFACE)
        col.add_widget(self._label)
        col.add_widget(self._value)
        self.add_widget(col)
        self.add_widget(_icon_cell("menu-down"))

    def _sync(self, instance, _value) -> None:
        self._border.rounded_rectangle = (instance.x, instance.y, instance.width, instance.height, 14)

    def set_value(self, text: str) -> None:
        self._value.text = text

    # Kept so screens that used to read/write a plain-button `.text` keep working.
    @property
    def text(self) -> str:
        return self._value.text

    @text.setter
    def text(self, value: str) -> None:
        self._value.text = value


def picker_field(icon: str, label: str, value: str, on_release) -> PickerField:
    field = PickerField(icon, label, value)
    field.bind(on_release=lambda *_a: on_release())
    return field


# --- M3 buttons --------------------------------------------------------------------

def primary_button(text: str, on_release=None, **kwargs) -> MDFillRoundFlatButton:
    """The main call-to-action for a screen (e.g. "Next: ..."). Filled, full brand color."""
    kwargs.setdefault("size_hint_x", 1)
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(48))
    btn = MDFillRoundFlatButton(text=text, md_bg_color=ACCENT, text_color=WHITE, **kwargs)
    if on_release:
        btn.bind(on_release=lambda *_a: on_release())
    return btn


def keep_focused_field_visible(scroll, form) -> None:
    """Scroll a form field above Android's soft keyboard when it receives focus."""
    def _scroll_to_field(field) -> None:
        # Wait for Android to resize the activity after it opens the keyboard.
        Clock.schedule_once(
            lambda _dt: scroll.scroll_to(field, padding=dp(24), animate=False), 0.15,
        )

    def _bind_text_fields(widget) -> None:
        if isinstance(widget, MDTextField):
            widget.bind(focus=lambda field, focused: _scroll_to_field(field) if focused else None)
        for child in widget.children:
            _bind_text_fields(child)

    _bind_text_fields(form)


def tonal_button(text: str, on_release=None, **kwargs) -> MDFillRoundFlatButton:
    """A secondary action worth noticing (SHOW CALCULATION, exports, toggles) --
    tonal fill so it doesn't compete with the screen's primary_button."""
    kwargs.setdefault("size_hint_x", 1)
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(44))
    btn = MDFillRoundFlatButton(text=text, md_bg_color=ACCENT_LIGHT, text_color=ON_PRIMARY_CONTAINER, **kwargs)
    if on_release:
        btn.bind(on_release=lambda *_a: on_release())
    return btn


def outlined_button(text: str, on_release=None, danger: bool = False, **kwargs) -> MDRoundFlatButton:
    """A low-emphasis action (New, Duplicate, Delete) -- outline only, no fill."""
    color = BAD_RED if danger else ACCENT
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(40))
    btn = MDRoundFlatButton(text=text, line_color=color, text_color=color, **kwargs)
    if on_release:
        btn.bind(on_release=lambda *_a: on_release())
    return btn


def header_actions(*widgets) -> MDBoxLayout:
    """A row of header-right actions sharing the screen_header's right_widget
    slot (e.g. an About icon alongside Save or Home). Plain BoxLayout doesn't
    center children on the cross-axis, so a row mixing e.g. a ~48dp icon button
    with a 36dp pill button would otherwise render them at visibly different
    vertical centers -- each widget gets the same AnchorLayout-cell centering
    _centered() already gives a lone right_widget."""
    row = MDBoxLayout(orientation="horizontal", spacing=dp(4), size_hint=(None, 1))
    row.bind(minimum_width=row.setter("width"))
    for w in widgets:
        # Header actions are icon buttons. Fixed compact cells prevent a hidden
        # Home icon or the phantom width left behind by an empty Save text label.
        row.add_widget(_centered(w, width=dp(44)))
    return row


def save_button(on_release=None, **kwargs) -> MDIconButton:
    """An icon-only Save action with no unused text/pill space."""
    return icon_button("content-save", on_release=on_release, color=ACCENT, **kwargs)


def save_current_project() -> bool:
    """Save the active quote from any wizard step through the shared Client screen."""
    from kivymd.app import MDApp

    app = MDApp.get_running_app()
    saved = app.root.get_screen("client").save_full_quote()
    if saved:
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.dialog import MDDialog

        dialog = MDDialog(
            title="Saved",
            text="This solar quote has been saved.",
            buttons=[MDFlatButton(
                text="OK", text_color=ACCENT, on_release=lambda *_args: dialog.dismiss(),
            )],
        )
        dialog.open()
    return saved


def go_home() -> None:
    """Return from any wizard step to Client Information."""
    from kivymd.app import MDApp

    MDApp.get_running_app().root.current = "client"


def icon_button(icon: str, on_release=None, color=ON_SURFACE_VARIANT, **kwargs) -> MDIconButton:
    btn = MDIconButton(icon=icon, theme_text_color="Custom", text_color=color, **kwargs)
    if on_release:
        btn.bind(on_release=lambda *_a: on_release())
    return btn


def about_button(on_release) -> MDIconButton:
    """The info icon every screen's header carries through to the About screen."""
    return icon_button("information-outline", on_release=on_release, color=ACCENT)


def nav_row(on_back, next_text: str, on_next) -> MDBoxLayout:
    """The bottom Back + Next pair for a wizard step -- Back is a fixed-width,
    low-emphasis outlined button (the top-left header arrow already covers this
    action; this is a second, thumb-reachable copy of it). Both actions are
    grouped at the right edge, where the primary Next action is easiest to
    reach. They share an explicit height because outlined_button and
    primary_button default to different heights."""
    row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(68))
    row.add_widget(Widget())
    row.add_widget(outlined_button("Back", on_release=on_back, size_hint_x=None, width=dp(158), height=dp(68)))
    row.add_widget(primary_button(
        next_text, on_release=on_next, size_hint_x=None, width=dp(158), height=dp(68),
    ))
    return row


def bottom_primary_action(text: str, on_release) -> MDBoxLayout:
    """A single bottom-page primary action aligned with the wizard controls."""
    row = MDBoxLayout(size_hint_y=None, height=dp(56))
    row.add_widget(Widget())
    row.add_widget(primary_button(
        text, on_release=on_release, size_hint_x=None, width=dp(210), height=dp(56),
    ))
    return row


def bottom_back_action(on_back) -> MDBoxLayout:
    """A bottom-page Back button matching the wizard action sizing."""
    row = MDBoxLayout(size_hint_y=None, height=dp(64))
    row.add_widget(Widget())
    row.add_widget(outlined_button(
        "Back", on_release=on_back, size_hint_x=None, width=dp(158), height=dp(64),
    ))
    return row


def section_card(icon: str, title: str) -> MDBoxLayout:
    """A rounded, tonal-surface container with an icon-badge + title header. Add
    field rows and other content to the returned card via card.add_widget(...)."""
    card = MDBoxLayout(
        orientation="vertical", spacing=dp(14), padding=dp(16),
        size_hint_y=None,
    )
    card.bind(minimum_height=card.setter("height"))
    with card.canvas.before:
        Color(*SURFACE_CONTAINER)
        card_rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(20)])

    def _sync_card(instance, _value):
        card_rect.pos = instance.pos
        card_rect.size = instance.size

    card.bind(pos=_sync_card, size=_sync_card)

    header = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(30))
    badge = AnchorLayout(
        anchor_x="center", anchor_y="center", size_hint=(None, None), size=(dp(30), dp(30)),
    )
    with badge.canvas.before:
        Color(*ACCENT_LIGHT)
        badge_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(10)])

    def _sync_badge(instance, _value):
        badge_rect.pos = instance.pos
        badge_rect.size = instance.size

    badge.bind(pos=_sync_badge, size=_sync_badge)
    badge.add_widget(MDIcon(
        icon=icon, theme_text_color="Custom", text_color=ON_PRIMARY_CONTAINER,
        size_hint=(None, None), size=(dp(17), dp(17)),
    ))
    header.add_widget(badge)
    header.add_widget(MDLabel(
        text=title.upper(), bold=True, theme_text_color="Custom", text_color=ON_SURFACE,
    ))
    card.add_widget(header)
    return card


def stat_title_label(text: str, fg=TEXT_DARK) -> MDLabel:
    """A stat-tile caption ('Total Daily', 'Grid Buy/Sell', ...) that always stays
    on one line -- a caption that wraps unpredictably in a narrow column breaks the
    whole row's baseline against its siblings that didn't wrap (worse, Kivy can wrap
    mid-word with no hyphen). Shortening to an ellipsis instead keeps every tile in
    a row the same height regardless of how long its label is."""
    lbl = MDLabel(
        text=text, font_style="Caption", halign="center",
        theme_text_color="Custom", text_color=fg,
        shorten=True, shorten_from="right", max_lines=1,
    )
    lbl.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
    return lbl


def section_label(icon: str, title: str) -> MDBoxLayout:
    """A lightweight icon+title section header for content that shouldn't sit inside
    a tonal section_card -- charts, big data tables, dynamic warning lists, and the
    weather-tinted Simulation screen, where a flat SURFACE_CONTAINER card would either
    clash with custom theming or fight a widget's own dynamic sizing."""
    row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(24))
    row.add_widget(_icon_cell(icon, color=ACCENT, size=18, width=20))
    row.add_widget(MDLabel(
        text=title.upper(), bold=True, theme_text_color="Custom", text_color=ON_SURFACE,
    ))
    return row


def project_row(subtitle: str, value: str, on_switch, on_new, on_more) -> MDBoxLayout:
    """The de-emphasized project switcher row: current project name + New/overflow
    actions, styled as a tonal pill so it doesn't compete with the form below it."""
    row = MDBoxLayout(spacing=dp(10), padding=(dp(14), dp(8), dp(8), dp(8)), size_hint_y=None, height=dp(52))
    with row.canvas.before:
        Color(*SURFACE_CONTAINER)
        row_rect = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(14)])

    def _sync(instance, _value):
        row_rect.pos = instance.pos
        row_rect.size = instance.size

    row.bind(pos=_sync, size=_sync)

    row.add_widget(_icon_cell("file-document-outline", size=20, width=22))
    col = BoxLayout(orientation="vertical")
    col.add_widget(MDLabel(text=subtitle, font_style="Caption", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT))
    value_label = MDLabel(text=value, bold=True, theme_text_color="Custom", text_color=ON_SURFACE, shorten=True)
    col.add_widget(value_label)
    # Wrap the label column itself so tapping the project name/value opens the switcher.
    wrapper = _Tappable(on_switch)
    wrapper.add_widget(col)
    row.add_widget(wrapper)

    row.add_widget(_centered(icon_button("plus", on_new), width=dp(40)))
    row.add_widget(_centered(icon_button("dots-vertical", on_more), width=dp(40)))
    row._value_label = value_label
    return row


class _Tappable(ButtonBehavior, BoxLayout):
    def __init__(self, on_release, **kwargs):
        super().__init__(**kwargs)
        self.bind(on_release=lambda *_a: on_release())


# --- Paywall / upgrade dialog ---------------------------------------------------

def _show_simple_message(title: str, text: str) -> None:
    """Show a simple OK dialog (used by paywall and other screens)."""
    from kivymd.uix.button import MDFlatButton
    from kivymd.uix.dialog import MDDialog

    dialog = MDDialog(
        title=title, text=text,
        buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: dialog.dismiss())],
    )
    dialog.open()


def show_paywall(screen, reason: str = "", on_change=None) -> None:
    """Show an upgrade dialog for free-tier limitations."""
    from kivymd.uix.button import MDFlatButton
    from kivymd.uix.dialog import MDDialog

    from db import database

    tier = database.get_tier()
    trial_end = database.get_trial_end()

    if tier == "pro":
        _show_simple_message("Already Pro", "You already have SolarQuote Pro!")
        return

    # Check if user has an active trial
    if trial_end:
        from datetime import date
        try:
            end = date.fromisoformat(trial_end)
            if date.today() <= end:
                remaining = (end - date.today()).days
                _show_simple_message(
                    "Free Trial Active",
                    f"You have {remaining} day(s) left in your free trial.\n\n"
                    "Upgrade to Pro to keep all features after your trial ends.",
                )
                return
        except (TypeError, ValueError):
            pass

    # Get billing manager
    try:
        from kivymd.app import MDApp
        billing = MDApp.get_running_app().billing
        monthly_price = billing.get_monthly_price()
        yearly_price = billing.get_yearly_price()
        yearly_savings = billing.get_yearly_savings()
    except Exception:
        monthly_price = "P299/month"
        yearly_price = "P2,990/year"
        yearly_savings = "Save 17%"
        billing = None

    text = "Unlock all SolarQuote Pro features:\n\n"
    text += "- Unlimited saved projects\n"
    text += "- Export PDF, Excel, CSV & PowerPoint\n"
    text += "- No watermark on reports\n"
    text += "- 7-day free trial\n\n"
    text += f"Monthly: {monthly_price}\n"
    text += f"Yearly: {yearly_price} ({yearly_savings})"

    if reason:
        text = f"{reason}\n\n{text}"

    def _dismiss(*_args):
        dialog.dismiss()

    def _refresh_all_labels():
        if on_change:
            on_change()
        try:
            from kivymd.app import MDApp
            MDApp.get_running_app().root.refresh_plan_label()
        except Exception:
            pass

    def _start_trial(*_args):
        dialog.dismiss()
        if billing:
            billing.start_trial()
        else:
            from datetime import date, timedelta
            end = date.today() + timedelta(days=7)
            database.set_trial_end(end.isoformat())
            database.set_tier("pro")
        _refresh_all_labels()
        _show_simple_message(
            "Trial Started",
            "Your 7-day free trial has started!\n\n"
            "All Pro features are now unlocked.",
        )

    def _subscribe_monthly(*_args):
        dialog.dismiss()
        _refresh_all_labels()
        if billing:
            billing.launch_purchase("solarquote_pro_monthly")

    def _subscribe_yearly(*_args):
        dialog.dismiss()
        if billing:
            billing.launch_purchase("solarquote_pro_yearly")

    buttons = [
        MDFlatButton(text="Not Now", text_color=ACCENT, on_release=_dismiss),
    ]

    if not trial_end:
        buttons.append(
            MDFlatButton(text="Start Free Trial", text_color=ACCENT, on_release=_start_trial),
        )

    buttons.append(
        MDFlatButton(text="Subscribe", text_color=ACCENT, on_release=_subscribe_monthly),
    )

    dialog = MDDialog(
        title="Upgrade to Pro",
        text=text,
        buttons=buttons,
    )
    dialog.open()
