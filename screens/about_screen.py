"""About screen: version/build info, contact, and legal links.

Reached from an info icon on the Client Information screen (not the onboarding
screen -- onboarding is a one-time introduction to the app's purpose, while
this is reference information someone looks up later, so it belongs somewhere
persistent and revisitable instead of a screen you only see once at cold start).

A "rate this app" entry is intentionally left out until the app has an actual
Play Store listing to link to -- a rate button that opens nothing/fails would
be worse than no button.
"""

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.screen import MDScreen

from ui_style import (
    ACCENT, APP_VERSION, BUILD_LABEL, LOGO_PATH, ON_SURFACE, ON_SURFACE_VARIANT,
    screen_header, section_card,
)

DEVELOPER_NAME = "SumClarTech"
CONTACT_EMAIL = "sumclartech@gmail.com"


class _LinkRow(ButtonBehavior, MDBoxLayout):
    def __init__(self, icon: str, label: str, **kwargs):
        kwargs.setdefault("spacing", dp(10))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(40))
        super().__init__(**kwargs)
        icon_cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(22))
        icon_cell.add_widget(MDIcon(
            icon=icon, theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
            size_hint=(None, None), size=(dp(18), dp(18)),
        ))
        self.add_widget(icon_cell)
        self.add_widget(MDLabel(text=label, theme_text_color="Custom", text_color=ON_SURFACE))
        chevron_cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(22))
        chevron_cell.add_widget(MDIcon(
            icon="chevron-right", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
            size_hint=(None, None), size=(dp(18), dp(18)),
        ))
        self.add_widget(chevron_cell)


class AboutScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "about"
        self._dialog: MDDialog | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header("About", step=None, on_back=self._go_back))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        header = BoxLayout(spacing=dp(12), size_hint_y=None, height=dp(56))
        logo_cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(56))
        logo_cell.add_widget(Image(source=LOGO_PATH, size_hint=(None, None), size=(dp(48), dp(48))))
        header.add_widget(logo_cell)
        name_col = MDBoxLayout(orientation="vertical")
        name_col.add_widget(MDLabel(
            text="SolarQuote", bold=True, font_style="H6",
            theme_text_color="Custom", text_color=ON_SURFACE,
        ))
        name_col.add_widget(MDLabel(
            text=f"Version {APP_VERSION} · Build {BUILD_LABEL}", font_style="Caption",
            theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
        ))
        header.add_widget(name_col)
        form.add_widget(header)

        contact_card = section_card("email-outline", "Contact & Support")
        contact_row = _LinkRow("domain", DEVELOPER_NAME)
        contact_row.bind(on_release=lambda *_: self._show_notice(
            "Contact", f"Developed by {DEVELOPER_NAME}\nReach us at: {CONTACT_EMAIL}",
        ))
        contact_card.add_widget(contact_row)
        form.add_widget(contact_card)

        legal_card = section_card("gavel", "Legal")
        tos_row = _LinkRow("file-document-outline", "Terms of Service")
        tos_row.bind(on_release=lambda *_: self._go_to("terms"))
        legal_card.add_widget(tos_row)
        privacy_row = _LinkRow("shield-lock-outline", "Privacy Policy")
        privacy_row.bind(on_release=lambda *_: self._go_to("privacy"))
        legal_card.add_widget(privacy_row)
        form.add_widget(legal_card)

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _show_notice(self, title: str, text: str) -> None:
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_to(self, screen_name: str) -> None:
        MDApp.get_running_app().root.current = screen_name

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = app.state.about_return_to
