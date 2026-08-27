from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.spinner import MDSpinner

from app_state import AppState
from billing import BillingManager
from db import database
from screens.about_screen import AboutScreen
from screens.battery_screen import BatteryScreen
from screens.client_screen import ClientScreen
from screens.consumption_screen import ConsumptionScreen
from screens.legal_screen import PrivacyScreen, TermsScreen
from screens.onboarding_screen import OnboardingScreen
from screens.report_screen import ReportScreen
from screens.roi_screen import RoiScreen
from screens.simulation_screen import SimulationScreen
from screens.solar_screen import SolarScreen
from screens.system_design_screen import SystemDesignScreen


class LoadingScreenManager(MDScreenManager):
    """Briefly acknowledge every in-app navigation with a centered spinner."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._spinner_overlay = None
        self._dismiss_event = None
        self._plan_label = None

    def refresh_plan_label(self) -> None:
        """Update the plan label text based on current tier/trial status."""
        if not self._plan_label:
            return

        tier = database.get_tier()
        trial_end = database.get_trial_end()

        if tier == "pro":
            if trial_end:
                from datetime import date
                try:
                    end = date.fromisoformat(trial_end)
                    remaining = (end - date.today()).days
                    if remaining > 0:
                        self._plan_label.text = f"Pro (Trial - {remaining}d left)"
                    else:
                        self._plan_label.text = "Pro"
                except (TypeError, ValueError):
                    self._plan_label.text = "Pro"
            else:
                self._plan_label.text = "Pro"
        else:
            self._plan_label.text = "Free"

    def show_navigation_loading(self, *_args) -> None:
        if self._dismiss_event:
            self._dismiss_event.cancel()
        if self._spinner_overlay and self._spinner_overlay.parent:
            self._spinner_overlay.parent.remove_widget(self._spinner_overlay)
        self._spinner_overlay = AnchorLayout(anchor_x='center', anchor_y='center')
        self._spinner_overlay.add_widget(
            MDSpinner(size_hint=(None, None), size=(dp(48), dp(48)), active=True)
        )
        self.current_screen.add_widget(self._spinner_overlay)
        self._dismiss_event = Clock.schedule_once(self._dismiss_loading, 0.35)

    def _dismiss_loading(self, _dt) -> None:
        if self._spinner_overlay and self._spinner_overlay.parent:
            self._spinner_overlay.parent.remove_widget(self._spinner_overlay)
        self._spinner_overlay = None


class StartupLoadingScreen(MDScreen):
    """Visible bridge between Android's native splash and the first app screen."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "startup_loading"
        center = AnchorLayout(anchor_x='center', anchor_y='center')
        center.add_widget(MDSpinner(size_hint=(None, None), size=(dp(48), dp(48)), active=True))
        self.add_widget(center)


class AppRoot(BoxLayout):
    """Wraps the screen manager + plan label; exposes .current for screen navigation."""
    current = StringProperty("")

    def __init__(self, screen_manager, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._sm = screen_manager
        self.add_widget(screen_manager)
        screen_manager.bind(current=self._sync_current)

    def refresh_plan_label(self) -> None:
        self._sm.refresh_plan_label()

    def get_screen(self, name: str):
        return self._sm.get_screen(name)

    def _sync_current(self, _inst, value):
        self.current = value

    def _set_screen(self, _inst, value):
        self._sm.current = value

    def on_current(self, _inst, value):
        if self._sm.current != value:
            self._sm.current = value


class SolarClientFinderApp(MDApp):
    def build(self):
        self.title = "SolarQuote"
        self.state = AppState()
        self.billing = BillingManager()
        database.configure(self.user_data_dir)
        database.init_db()
        self.billing.initialize()
        show_onboarding = database.consume_first_launch()

        self.theme_cls.primary_palette = "Green"

        self._show_onboarding = show_onboarding
        self._screen_manager = LoadingScreenManager()

        self._plan_label = MDLabel(
            text="Free",
            font_style="Caption",
            halign="center",
            size_hint_y=None,
            height=dp(24),
            theme_text_color="Custom",
            text_color=(0, 0, 0, 1),
        )
        with self._plan_label.canvas.before:
            from kivy.graphics import Color, Rectangle
            self._plan_label_color = Color(0.85, 0.95, 0.85, 1)
            self._plan_label_bg = Rectangle(pos=self._plan_label.pos, size=self._plan_label.size)

        def _sync_bg(instance, _value):
            self._plan_label_bg.pos = instance.pos
            self._plan_label_bg.size = instance.size

        self._plan_label.bind(pos=_sync_bg, size=_sync_bg)
        self._screen_manager._plan_label = self._plan_label
        self._screen_manager.refresh_plan_label()

        root = AppRoot(self._screen_manager)
        root.add_widget(self._plan_label)

        self._screen_manager.add_widget(StartupLoadingScreen())
        self._screen_manager.current = "startup_loading"
        Clock.schedule_once(self._build_app_screens, 0.1)
        return root

    def _build_app_screens(self, _dt) -> None:
        sm = self._screen_manager
        sm.add_widget(OnboardingScreen())
        sm.add_widget(ClientScreen())
        sm.add_widget(AboutScreen())
        sm.add_widget(TermsScreen())
        sm.add_widget(PrivacyScreen())
        sm.add_widget(ConsumptionScreen())
        sm.add_widget(SolarScreen())
        sm.add_widget(BatteryScreen())
        sm.add_widget(SystemDesignScreen())
        sm.add_widget(SimulationScreen())
        sm.add_widget(RoiScreen())
        sm.add_widget(ReportScreen())
        sm.bind(current=sm.show_navigation_loading)
        sm.bind(current=self._on_screen_change)
        sm.current = "onboarding" if self._show_onboarding else "client"

    MAIN_SCREENS = {"client", "consumption", "solar", "battery", "system_design", "simulation", "roi", "report"}

    def _on_screen_change(self, _inst, screen_name: str) -> None:
        self._plan_label.opacity = 1 if screen_name in self.MAIN_SCREENS else 0


if __name__ == "__main__":
    SolarClientFinderApp().run()
