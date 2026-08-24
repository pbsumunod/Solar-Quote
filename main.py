from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

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


class SolarClientFinderApp(MDApp):
    def build(self):
        self.title = "SolarQuote"
        self.state = AppState()
        database.configure(self.user_data_dir)
        database.init_db()
        show_onboarding = database.consume_first_launch()

        self.theme_cls.primary_palette = "Green"

        sm = MDScreenManager()
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
        return sm


if __name__ == "__main__":
    SolarClientFinderApp().run()
