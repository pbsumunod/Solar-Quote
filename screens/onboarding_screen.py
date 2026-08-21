"""Onboarding screen: a brief introduction shown before the Client Information
wizard starts, so a first-time installer knows what the app does and how the
8-step flow is organized before they're asked to type anything.
"""

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from ui_style import ACCENT, LOGO_PATH, ON_SURFACE, ON_SURFACE_VARIANT, primary_button, section_card

FEATURES = [
    ("auto-fix", "Auto-Sized Systems",
     "Battery, inverter, and panel array sizing computed automatically from fixed spec catalogs."),
    ("weather-partly-cloudy", "Weather Simulation",
     "Hour-by-hour solar, battery, and grid flow across Sunny, Cloudy, and Rainy scenarios."),
    ("chart-line", "ROI & Payback",
     "A multi-year financial projection with configurable inflation and export rates."),
    ("file-export-outline", "Proposal Export",
     "PDF, Excel, CSV, and PowerPoint exports, ready to hand to a client."),
]


class OnboardingScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "onboarding"
        self._dialog: MDDialog | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(20), padding=(dp(24), dp(40), dp(24), dp(24)),
                            size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        logo_cell = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(72))
        logo_cell.add_widget(Image(source=LOGO_PATH, size_hint=(None, None), size=(dp(72), dp(72))))
        form.add_widget(logo_cell)
        form.add_widget(MDLabel(
            text="Welcome to SolarQuote", bold=True, font_style="H5", halign="center",
            theme_text_color="Custom", text_color=ON_SURFACE, size_hint_y=None, height=dp(36),
        ))
        tagline = MDLabel(
            text="Solar system sizing, ROI simulation, and client-ready proposals -- for installers.",
            halign="center", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT, size_hint_y=None,
        )
        tagline.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        tagline.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
        form.add_widget(tagline)

        for icon, title, desc in FEATURES:
            card = section_card(icon, title)
            desc_label = MDLabel(
                text=desc, theme_text_color="Custom", text_color=ON_SURFACE_VARIANT, size_hint_y=None,
            )
            desc_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
            desc_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
            card.add_widget(desc_label)
            form.add_widget(card)

        form.add_widget(primary_button("Get Started", on_release=self._get_started))

        about_cell = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(32))
        about_btn = MDFlatButton(text="About & Credits", text_color=ACCENT, on_release=lambda *_: self._show_credits())
        about_cell.add_widget(about_btn)
        form.add_widget(about_cell)

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _get_started(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "client"

    def _show_credits(self) -> None:
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="About SolarQuote",
            text=(
                "SolarQuote helps installers size solar + battery systems and generate "
                "client-ready proposals.\n\nContact the developer:\npamela.sumunod@gmail.com"
            ),
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()
