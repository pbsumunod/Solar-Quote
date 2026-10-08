"""About screen: version/build info, contact, and legal links.

Reached from an info icon on the Client Information screen (not the onboarding
screen -- onboarding is a one-time introduction to the app's purpose, while
this is reference information someone looks up later, so it belongs somewhere
persistent and revisitable instead of a screen you only see once at cold start).

A "rate this app" entry is intentionally left out until the app has an actual
Play Store listing to link to -- a rate button that opens nothing/fails would
be worse than no button.
"""

from kivy.clock import Clock
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
    primary_button, screen_header, section_card, tonal_button,
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
        self._restoring = False
        self._restore_timeout = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header("About", step=None, on_back=self._go_back))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        header = BoxLayout(spacing=dp(12), size_hint_y=None, height=dp(64))
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

        sub_card = section_card("crown", "Subscription")
        self._tier_row = _LinkRow("information", "Current Plan: Free")
        self._tier_row.bind(on_release=lambda *_: self._show_tier_details())
        sub_card.add_widget(self._tier_row)

        restore_row = _LinkRow("restore", "Restore Purchases")
        restore_row.bind(on_release=lambda *_: self._restore_purchases())
        sub_card.add_widget(restore_row)

        upgrade_row = _LinkRow("arrow-up-bold", "Upgrade to Pro")
        upgrade_row.bind(on_release=lambda *_: self._upgrade())
        sub_card.add_widget(upgrade_row)
        self._upgrade_row = upgrade_row

        form.add_widget(sub_card)

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

    def on_pre_enter(self) -> None:
        self._refresh_tier_display()

    def _refresh_tier_display(self) -> None:
        from db import database
        tier = database.get_tier()
        trial_end = database.get_trial_end()
        is_pro = tier == "pro"

        if is_pro:
            if trial_end:
                from datetime import date
                try:
                    end = date.fromisoformat(trial_end)
                    remaining = (end - database.get_trusted_today()).days
                    if remaining > 0:
                        plan_text = f"Current Plan: Pro (Trial - {remaining} days left)"
                    else:
                        plan_text = "Current Plan: Pro"
                except (TypeError, ValueError):
                    plan_text = "Current Plan: Pro"
            else:
                plan_text = "Current Plan: Pro"
        else:
            plan_text = "Current Plan: Free"

        self._tier_row.children[1].text = plan_text
        self._upgrade_row.opacity = 0 if is_pro else 1
        self._upgrade_row.disabled = is_pro
        self._upgrade_row.height = 0 if is_pro else dp(40)
        self._upgrade_row.size_hint_y = None

    def _show_tier_details(self) -> None:
        from db import database
        tier = database.get_tier()
        tier_text = "Pro (Active)" if tier == "pro" else "Free"
        self._show_notice(
            "Subscription",
            f"Current plan: {tier_text}\n\n"
            "Free: 3 projects, PDF only, watermark\n"
            "Pro: Unlimited projects, all formats, no watermark",
        )

    def _restore_purchases(self) -> None:
        if self._restoring:
            return
        self._restoring = True
        self._show_notice("Checking Purchases", "Checking Google Play for an active subscription...")
        self._restore_timeout = Clock.schedule_once(self._restore_timed_out, 15)
        try:
            billing = MDApp.get_running_app().billing
            billing.restore_purchases(on_complete=self._on_restore_complete)
        except Exception:
            self._on_restore_complete(None)

    def _on_restore_complete(self, result: bool | None) -> None:
        # Play callbacks may arrive on a Java thread. Widgets belong to Kivy's thread.
        Clock.schedule_once(lambda _dt: self._finish_restore(result), 0)

    def _finish_restore(self, result: bool | None) -> None:
        if not self._restoring:
            return
        self._restoring = False
        if self._restore_timeout:
            self._restore_timeout.cancel()
            self._restore_timeout = None
        self._refresh_tier_display()
        if result is True:
            self._show_notice("Restored", "Your Pro subscription has been restored!")
        elif result is False:
            self._show_notice("No Purchases", "No active subscription was found for this Google Play account.")
        else:
            self._show_notice("Restore Unavailable", "Could not check Google Play. Please try again later.")

    def _restore_timed_out(self, _dt) -> None:
        self._restore_timeout = None
        self._finish_restore(None)

    def _upgrade(self) -> None:
        from ui_style import show_paywall
        show_paywall(self, on_change=self._refresh_tier_display)
