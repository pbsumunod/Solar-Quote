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
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from ui_style import LOGO_PATH, ON_SURFACE, ON_SURFACE_VARIANT, primary_button, section_card

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
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(10), padding=(dp(24), dp(20), dp(24), dp(28)),
                            size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        logo_cell = AnchorLayout(anchor_x="center", anchor_y="center", size_hint_y=None, height=dp(204))
        logo_cell.add_widget(Image(source=LOGO_PATH, size_hint=(None, None), size=(dp(192), dp(192))))
        form.add_widget(logo_cell)
        welcome = MDLabel(
            text="Plan every solar quote with confidence", bold=True, font_style="H4", halign="center",
            theme_text_color="Custom", text_color=ON_SURFACE, size_hint_y=None,
        )
        welcome.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        welcome.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp(4)))
        form.add_widget(welcome)
        tagline = MDLabel(
            text="Solar sizing, financial modeling, and polished proposals - all in one guided workflow.",
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

        cta_cell = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(56))
        cta_cell.add_widget(primary_button(
            "Start a Solar Quote", on_release=self._get_started, size_hint_x=None, width=dp(240), height=dp(56),
        ))
        form.add_widget(cta_cell)

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _get_started(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "client"
