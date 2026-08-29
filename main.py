import logging

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.spinner import MDSpinner

from app_state import AppState
from billing import BillingManager
import internet_time
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

log = logging.getLogger(__name__)


def _android_system_bar_insets() -> tuple:
    """(top_dp, bottom_dp) padding needed to clear the status bar and
    navigation bar on Android.

    Apps targeting API 35 (Android 15) get edge-to-edge display enforced
    unconditionally -- content draws behind the system bars whether the app
    asked for it or not. A previous version of this code assumed a manifest
    attribute could opt back out of that; checked directly against Android's
    edge-to-edge developer guide, there is no such opt-out. Apps must handle
    insets themselves, full stop. Kivy 2.3/KivyMD 1.2 have no built-in
    WindowInsets support, so this reads the system bar dimensions directly
    from Android's own resources (the same values the OS itself uses to
    reserve that space) and the caller pads the root layout by that amount.

    This is a one-time query at startup, not a live WindowInsets listener --
    good enough since the app is portrait-locked (orientation = portrait in
    buildozer.spec) so these dimensions don't change mid-session on a given
    device. Falls back to (0, 0) on non-Android or if anything goes wrong,
    so a lookup failure just means no padding rather than a crash.
    """
    if platform != "android":
        return 0, 0
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        resources = activity.getResources()
        density = resources.getDisplayMetrics().density

        def _dimen_dp(name: str) -> float:
            res_id = resources.getIdentifier(name, "dimen", "android")
            if res_id == 0:
                return 0.0
            return resources.getDimensionPixelSize(res_id) / density

        return _dimen_dp("status_bar_height"), _dimen_dp("navigation_bar_height")
    except Exception as exc:
        log.warning("Could not read Android system bar insets: %s", exc)
        return 0, 0


# ui_style.keep_focused_field_visible() scrolls a focused field above the
# Android keyboard by calling ScrollView.scroll_to() -- but that can only
# compute a correct position if Kivy's own Window.height has actually
# shrunk to account for the keyboard. AndroidManifest's windowSoftInputMode
# (set to "adjustResize" in p4a_hooks.py) only tells ANDROID to resize the
# activity; Kivy's SDL2 layer needs its own, separate softinput_mode set to
# translate that into a Window resize it and everything built on it (every
# ScrollView, every scroll_to() call) can actually see. Left unset (the
# default), Kivy does nothing on its own when the keyboard opens, so
# scroll_to() was scrolling within a Window that, as far as Kivy knew,
# hadn't changed size at all. "resize" (not "pan"/"below_target", Kivy's own
# built-in panning modes) is the one that only changes what Window.height
# reports rather than also independently panning content itself -- picked
# specifically to complement keep_focused_field_visible's own scrolling
# instead of fighting it with a second, competing adjustment.
Window.softinput_mode = "resize"

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
                    remaining = (date.fromisoformat(trial_end) - database.get_trusted_today()).days
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
        internet_time.init()
        show_onboarding = database.consume_first_launch()

        self.theme_cls.primary_palette = "Green"

        self._show_onboarding = show_onboarding
        self._screen_manager = LoadingScreenManager()
        # Play Billing callbacks (a purchase completing, a trial being
        # confirmed) land asynchronously, on whatever thread pyjnius delivers
        # them on -- not necessarily Kivy's main thread -- and can arrive
        # well after this screen manager already exists and is on screen.
        # Without this, the persistent plan label would keep showing "Free"
        # after a real purchase until the user happened to navigate
        # somewhere that re-reads the tier on its own (e.g. About).
        self.billing.on_tier_changed = self._on_billing_tier_changed

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
        top_inset, bottom_inset = _android_system_bar_insets()
        root.padding = (0, dp(top_inset), 0, dp(bottom_inset))
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

    def _on_billing_tier_changed(self) -> None:
        """billing.py calls this after a confirmed Play purchase changes the
        tier. May be called from a non-Kivy thread, so touch no widgets here
        directly -- schedule the actual refresh onto Kivy's main thread."""
        Clock.schedule_once(lambda _dt: self._screen_manager.refresh_plan_label())


if __name__ == "__main__":
    SolarClientFinderApp().run()
