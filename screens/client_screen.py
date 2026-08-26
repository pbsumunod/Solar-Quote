"""Client Information screen (ported from the desktop app's ui/client.py; redesigned
to the Material 3 visual language established by the "SolarQuote Client Screen"
mockup -- see ui_style.py for the shared components this and every other screen use).

Two-column desktop layout becomes a single scrollable column; QComboBox project/ratio
pickers become MDDropdownMenu; QDateEdit becomes a plain text field defaulting to today
(a real date picker is deferred, per the Phase 1 plan). Validation and the
Project.to_fields()/from_row() round-trip are unchanged from the desktop version --
that logic was never Qt-specific.
"""

import json
import re
from datetime import date

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from db import database
from logic.geo_data import COUNTRY_LATITUDES
from logic.models import Project
from ui_style import (
    ACCENT, ON_SURFACE_VARIANT, about_button, bottom_primary_action, header_actions, keep_focused_field_visible, m3_field, picker_field, primary_button, save_button, save_current_project,
    project_row, screen_header, section_card, show_paywall,
)

DAY_NIGHT_RATIOS = ["10/90", "20/80", "30/70", "40/60", "50/50", "60/40", "70/30", "80/20", "90/10"]
DEFAULT_ELECTRICITY_RATE = 14.50
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The other 6 wizard steps, in the order their state is nested under a saved
# project's quote_data JSON blob -- Client Info itself is already covered by
# the project's own plain columns, so it isn't included here.
QUOTE_STEP_SCREENS = ["consumption", "solar", "battery", "system_design", "simulation", "roi"]


class ClientScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "client"
        self.current_project_id: int | None = None
        self._daytime_pct = 70
        self._country = "Philippines"
        self._dialog: MDDialog | None = None
        self._project_menu: MDDropdownMenu | None = None
        self._overflow_menu: MDDropdownMenu | None = None
        self._ratio_menu: MDDropdownMenu | None = None
        self._country_menu: MDDropdownMenu | None = None

        self._build_ui()
        self._new_project()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(
            "Client Information", step=1, show_logo=True,
            right_widget=header_actions(about_button(self._go_about), save_button(on_release=save_current_project)),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        self.project_row_widget = project_row(
            "CURRENT PROJECT", "Unsaved new project",
            on_switch=self._open_project_menu, on_new=lambda: self._new_project(),
            on_more=self._open_overflow_menu,
        )
        form.add_widget(self.project_row_widget)

        client_card = section_card("card-account-details-outline", "Client Details")
        self.client_name_field = m3_field("Client Name *", icon="account")
        self.project_location_field = m3_field("Project Location", icon="map-marker")
        client_card.add_widget(self.client_name_field)
        client_card.add_widget(self.project_location_field)

        self.country_field = picker_field("earth", "Country", "Philippines", self._open_country_menu)
        client_card.add_widget(self.country_field)
        client_card.add_widget(MDLabel(
            text="Tap to search 150+ countries -- sets solar-harvest scaling",
            font_style="Caption", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
            size_hint_y=None, height=dp(16),
        ))

        contact_date_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.contact_number_field = m3_field("Contact No.", icon="phone", input_filter="int")
        self.date_field = m3_field("Date", icon="calendar", text=date.today().isoformat())
        contact_date_row.add_widget(self.contact_number_field)
        contact_date_row.add_widget(self.date_field)
        client_card.add_widget(contact_date_row)

        self.email_field = m3_field("Email", icon="email")
        client_card.add_widget(self.email_field)
        form.add_widget(client_card)

        electricity_card = section_card("lightning-bolt", "Electricity Usage")
        kwh_rate_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.monthly_kwh_field = m3_field("Monthly (kWh) *", icon="lightning-bolt", input_filter="float")
        self.electricity_rate_field = m3_field(
            "Rate (PHP/kWh)", icon="cash", input_filter="float", text=f"{DEFAULT_ELECTRICITY_RATE:.2f}",
        )
        kwh_rate_row.add_widget(self.monthly_kwh_field)
        kwh_rate_row.add_widget(self.electricity_rate_field)
        electricity_card.add_widget(kwh_rate_row)

        self.ratio_field = picker_field("scale-balance", "Day / Night Consumption Split", "70% / 30%",
                                         self._open_ratio_menu)
        electricity_card.add_widget(self.ratio_field)
        form.add_widget(electricity_card)

        form.add_widget(bottom_primary_action("Next: Consumption", self._go_next))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _open_ratio_menu(self) -> None:
        items = [
            {"text": ratio, "on_release": lambda r=ratio: self._select_ratio(r)}
            for ratio in DAY_NIGHT_RATIOS
        ]
        self._ratio_menu = MDDropdownMenu(caller=self.ratio_field, items=items, width_mult=3)
        self._ratio_menu.open()

    def _select_ratio(self, ratio: str) -> None:
        self._daytime_pct = int(ratio.split("/")[0])
        self.ratio_field.set_value(f"{ratio.split('/')[0]}% / {ratio.split('/')[1]}%")
        if self._ratio_menu:
            self._ratio_menu.dismiss()

    def _open_country_menu(self) -> None:
        items = [
            {"text": country, "on_release": lambda c=country: self._select_country(c)}
            for country in sorted(COUNTRY_LATITUDES.keys())
        ]
        self._country_menu = MDDropdownMenu(caller=self.country_field, items=items, width_mult=4, max_height=dp(360))
        self._country_menu.open()

    def _select_country(self, country: str) -> None:
        self._country = country
        self.country_field.set_value(country)
        if self._country_menu:
            self._country_menu.dismiss()

    def _open_project_menu(self) -> None:
        items = [{"text": "(Unsaved new project)", "on_release": lambda: self._select_project(None)}]
        for row in database.list_projects():
            label = f"{row['client_name'] or '(Untitled)'} - {row['project_date']}"
            items.append({"text": label, "on_release": lambda pid=row["id"]: self._select_project(pid)})
        self._project_menu = MDDropdownMenu(caller=self.project_row_widget, items=items, width_mult=4)
        self._project_menu.open()

    def _select_project(self, project_id: int | None) -> None:
        if self._project_menu:
            self._project_menu.dismiss()
        if project_id is None:
            self._new_project()
            return
        row = database.get_project(project_id)
        if row is not None:
            self._apply_project(Project.from_row(row))
            self._apply_quote_data(row["quote_data"])

    def _open_overflow_menu(self) -> None:
        items = [
            {"text": "Duplicate", "on_release": lambda: self._overflow_action(self._duplicate_project)},
            {"text": "Delete", "on_release": lambda: self._overflow_action(self._delete_project)},
        ]
        self._overflow_menu = MDDropdownMenu(caller=self.project_row_widget, items=items, width_mult=3)
        self._overflow_menu.open()

    def _overflow_action(self, action) -> None:
        if self._overflow_menu:
            self._overflow_menu.dismiss()
        action()

    def _collect_project(self) -> Project:
        return Project(
            id=self.current_project_id,
            client_name=self.client_name_field.text.strip(),
            project_location=self.project_location_field.text.strip(),
            contact_number=self.contact_number_field.text.strip(),
            email=self.email_field.text.strip(),
            project_date=self.date_field.text.strip(),
            notes="",
            monthly_kwh=float(self.monthly_kwh_field.text or 0),
            daytime_ratio_pct=self._daytime_pct,
            electricity_rate=float(self.electricity_rate_field.text or 0),
            country=self._country,
        )

    def _apply_project(self, project: Project) -> None:
        self.client_name_field.text = project.client_name
        self.project_location_field.text = project.project_location
        self.contact_number_field.text = project.contact_number
        self.email_field.text = project.email
        self.date_field.text = project.project_date or date.today().isoformat()
        self.monthly_kwh_field.text = f"{project.monthly_kwh:.2f}"
        self._daytime_pct = project.daytime_ratio_pct
        self.ratio_field.set_value(f"{project.daytime_ratio_pct}% / {project.nighttime_ratio_pct}%")
        self.electricity_rate_field.text = f"{project.electricity_rate:.2f}"
        self._country = project.country
        self.country_field.set_value(project.country or "Select Country")
        self.current_project_id = project.id
        if project.id is not None:
            self.project_row_widget._value_label.text = f"{project.client_name} - {project.project_date}"

    def get_report_data(self) -> dict:
        project = self._collect_project()
        return {
            "client_name": project.client_name,
            "project_location": project.project_location,
            "contact_number": project.contact_number,
            "email": project.email,
            "project_date": project.project_date,
            "notes": "",
            "monthly_kwh": project.monthly_kwh,
            "daytime_pct": project.daytime_ratio_pct,
            "nighttime_pct": project.nighttime_ratio_pct,
            "electricity_rate": project.electricity_rate,
            "country": project.country,
        }

    def _validate(self, project: Project) -> str | None:
        if not project.client_name:
            return "Client Name is required."
        if project.monthly_kwh <= 0:
            return "Latest Monthly Electricity Consumption must be greater than 0."
        if project.electricity_rate < 0:
            return "Electricity Rate cannot be negative."
        if project.email and not EMAIL_PATTERN.match(project.email):
            return "Email is not a valid email address."
        return None

    def _show_message(self, title: str, text: str) -> None:
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[primary_button("OK", on_release=lambda: self._dialog.dismiss(), size_hint_x=None, width=dp(100))],
        )
        self._dialog.open()

    def _new_project(self) -> None:
        self._apply_project(Project(daytime_ratio_pct=70, electricity_rate=DEFAULT_ELECTRICITY_RATE))
        self.project_row_widget._value_label.text = "Unsaved new project"

    def _apply_quote_data(self, quote_data_json: str) -> None:
        """Restores Consumption through Savings & ROI's editable fields from a
        saved project's quote_data JSON blob (empty/legacy rows -- '{}' -- just
        reset every step to its own defaults, same as a brand new project)."""
        try:
            quote_data = json.loads(quote_data_json) if quote_data_json else {}
        except (TypeError, ValueError):
            quote_data = {}
        app = MDApp.get_running_app()
        for name in QUOTE_STEP_SCREENS:
            app.root.get_screen(name).apply_state(quote_data.get(name, {}))

    def _collect_quote_data(self) -> str:
        app = MDApp.get_running_app()
        quote_data = {name: app.root.get_screen(name).collect_state() for name in QUOTE_STEP_SCREENS}
        return json.dumps(quote_data)

    def save_full_quote(self) -> bool:
        """Persists the whole quote -- Client Info plus every step through Savings
        & ROI -- to the current (or a newly created) project row. Called from the
        Report screen's Save action, the last step, so a save always captures the
        full flow rather than only the Client Information fields entered first."""
        try:
            project = self._collect_project()
        except ValueError:
            self._show_message("Invalid Data", "Please enter valid numbers on the Client Information step.")
            return False
        error = self._validate(project)
        if error:
            self._show_message("Invalid Data", f"{error} (Client Information step)")
            return False

        fields = project.to_fields()
        fields["quote_data"] = self._collect_quote_data()
        if self.current_project_id is None:
            if database.get_tier() == "free" and database.count_projects() >= database.FREE_PROJECT_LIMIT:
                show_paywall(self, reason="Free tier limited to 3 saved projects.")
                return False
            self.current_project_id = database.create_project(fields)
        else:
            database.update_project(self.current_project_id, fields)

        row = database.get_project(self.current_project_id)
        self.project_row_widget._value_label.text = f"{row['client_name']} - {row['project_date']}"
        return True

    def _duplicate_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Save the current project before duplicating it.")
            return
        if database.get_tier() == "free" and database.count_projects() >= database.FREE_PROJECT_LIMIT:
            show_paywall(self, reason="Free tier limited to 3 saved projects.")
            return
        new_id = database.duplicate_project(self.current_project_id)
        row = database.get_project(new_id)
        self._apply_project(Project.from_row(row))
        self.project_row_widget._value_label.text = f"{row['client_name']} - {row['project_date']}"

    def _delete_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Select a saved project to delete.")
            return
        database.delete_project(self.current_project_id)
        self._new_project()

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _go_next(self) -> None:
        try:
            project = self._collect_project()
        except ValueError:
            self._show_message("Invalid Data", "Please enter valid numbers.")
            return
        error = self._validate(project)
        if error:
            self._show_message("Invalid Data", error)
            return
        app = MDApp.get_running_app()
        app.state.project = project
        app.root.current = "consumption"
