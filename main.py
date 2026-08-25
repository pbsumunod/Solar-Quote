from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.spinner import MDSpinner

from app_state import AppState
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


class SolarClientFinderApp(MDApp):
    def build(self):
        self.title = "SolarQuote"
        self.state = AppState()
        database.configure(self.user_data_dir)
        database.init_db()
        show_onboarding = database.consume_first_launch()

        self.theme_cls.primary_palette = "Green"

        self._show_onboarding = show_onboarding
        self._screen_manager = LoadingScreenManager()
        self._screen_manager.add_widget(StartupLoadingScreen())
        self._screen_manager.current = "startup_loading"
        # Return promptly so the loader paints before the heavy wizard screens
        # (charts, fields, and report controls) are constructed.
        Clock.schedule_once(self._build_app_screens, 0.1)
        return self._screen_manager

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
        sm.current = "onboarding" if self._show_onboarding else "client"
        # Bind after initial selection so app startup itself does not flash a modal.
        sm.bind(current=sm.show_navigation_loading)


if __name__ == "__main__":
    SolarClientFinderApp().run()
