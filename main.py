from kivy.clock import Clock
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
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
    """Briefly acknowledge every in-app navigation with a consistent spinner."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loading_dialog = None
        self._dismiss_event = None

    def show_navigation_loading(self, *_args) -> None:
        if self._dismiss_event:
            self._dismiss_event.cancel()
        if self._loading_dialog is None:
            content = MDBoxLayout(
                orientation="horizontal", spacing=16, padding=8, size_hint_y=None, height=48,
            )
            content.add_widget(MDSpinner(size_hint=(None, None), size=(32, 32), active=True))
            content.add_widget(MDLabel(text="Loading...", halign="center"))
            self._loading_dialog = MDDialog(
                title="", type="custom", content_cls=content, auto_dismiss=False,
            )
        if not self._loading_dialog.parent:
            Clock.schedule_once(lambda _dt: self._loading_dialog.open(), 0)
        self._dismiss_event = Clock.schedule_once(self._dismiss_loading, 0.35)

    def _dismiss_loading(self, _dt) -> None:
        if self._loading_dialog and self._loading_dialog.parent:
            self._loading_dialog.dismiss()


class SolarClientFinderApp(MDApp):
    def build(self):
        self.title = "SolarQuote"
        self.state = AppState()
        database.configure(self.user_data_dir)
        database.init_db()
        show_onboarding = database.consume_first_launch()

        self.theme_cls.primary_palette = "Green"

        sm = LoadingScreenManager()
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
        sm.current = "onboarding" if show_onboarding else "client"
        # Bind after initial selection so app startup itself does not flash a modal.
        sm.bind(current=sm.show_navigation_loading)
        return sm


if __name__ == "__main__":
    SolarClientFinderApp().run()
