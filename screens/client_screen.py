"""Client Information screen (ported from the desktop app's ui/client.py).

Two-column desktop layout becomes a single scrollable column; QComboBox project/ratio
pickers become MDDropdownMenu; QDateEdit becomes a plain text field defaulting to today
(a real date picker is deferred, per the Phase 1 plan). Validation and the
Project.to_fields()/from_row() round-trip are unchanged from the desktop version --
that logic was never Qt-specific.
"""

import re
from datetime import date

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from db import database
from logic.geo_data import COUNTRY_LATITUDES
from logic.models import Project
from ui_style import ACCENT, TEXT_DARK, WHITE, green_field, top_app_bar, with_bg

DAY_NIGHT_RATIOS = ["10/90", "20/80", "30/70", "40/60", "50/50", "60/40", "70/30", "80/20", "90/10"]
DEFAULT_ELECTRICITY_RATE = 14.50
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClientScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "client"
        self.current_project_id: int | None = None
        self._daytime_pct = 70
        self._country = "Philippines"
        self._dialog: MDDialog | None = None
        self._project_menu: MDDropdownMenu | None = None
        self._ratio_menu: MDDropdownMenu | None = None
        self._country_menu: MDDropdownMenu | None = None
        self._project_ids_by_index: list[int | None] = []

        self._build_ui()
        self._refresh_project_list()
        self._new_project()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(top_app_bar("Client Information"))

        scroll = ScrollView()
        form = MDBoxLayout(
            orientation="vertical", spacing=dp(6), padding=dp(10),
            size_hint_y=None,
        )
        form.bind(minimum_height=form.setter("height"))

        project_row = MDBoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None, height=dp(80))
        self.project_btn = MDRaisedButton(
            text="(Unsaved new project)", size_hint_x=1, md_bg_color=ACCENT, text_color=WHITE,
        )
        self.project_btn.bind(on_release=self._open_project_menu)
        project_row.add_widget(self.project_btn)
        actions_row = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(36))
        new_btn = MDFlatButton(text="New", text_color=ACCENT, on_release=lambda *_: self._new_project())
        save_btn = MDFlatButton(text="Save", text_color=ACCENT, on_release=lambda *_: self._save_project())
        dup_btn = MDFlatButton(text="Duplicate", text_color=ACCENT, on_release=lambda *_: self._duplicate_project())
        del_btn = MDFlatButton(text="Delete", text_color=ACCENT, on_release=lambda *_: self._delete_project())
        for b in (new_btn, save_btn, dup_btn, del_btn):
            actions_row.add_widget(b)
        project_row.add_widget(actions_row)
        form.add_widget(project_row)

        form.add_widget(MDLabel(
            text="Client Information", bold=True, size_hint_y=None, height=dp(24),
            theme_text_color="Custom", text_color=TEXT_DARK,
        ))
        self.client_name_field = green_field(hint_text="Client Name")
        self.project_location_field = green_field(hint_text="Project Location")
        form.add_widget(self.client_name_field)
        form.add_widget(self.project_location_field)

        # Country drives the Simulation tab's latitude-based solar harvest scaling.
        self.country_btn = MDRaisedButton(text="Philippines", size_hint_x=1, md_bg_color=ACCENT, text_color=WHITE)
        self.country_btn.bind(on_release=self._open_country_menu)
        form.add_widget(self.country_btn)

        # Short fields share a row -- each is a handful of characters, no need for full width.
        contact_date_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        self.contact_number_field = green_field(hint_text="Contact Number", input_filter="int")
        self.date_field = green_field(hint_text="Date (YYYY-MM-DD)", text=date.today().isoformat())
        contact_date_row.add_widget(self.contact_number_field)
        contact_date_row.add_widget(self.date_field)
        form.add_widget(contact_date_row)

        self.email_field = green_field(hint_text="Email")
        form.add_widget(self.email_field)

        form.add_widget(MDLabel(
            text="Electricity Information", bold=True, size_hint_y=None, height=dp(24),
            theme_text_color="Custom", text_color=TEXT_DARK,
        ))

        kwh_rate_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        self.monthly_kwh_field = green_field(hint_text="Monthly Consumption (kWh)", input_filter="float")
        self.electricity_rate_field = green_field(
            hint_text="Rate (PHP/kWh)", input_filter="float",
            text=f"{DEFAULT_ELECTRICITY_RATE:.2f}",
        )
        kwh_rate_row.add_widget(self.monthly_kwh_field)
        kwh_rate_row.add_widget(self.electricity_rate_field)
        form.add_widget(kwh_rate_row)

        ratio_row = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        self.ratio_btn = MDRaisedButton(text="Ratio: 70/30", md_bg_color=ACCENT, text_color=WHITE)
        self.ratio_btn.bind(on_release=self._open_ratio_menu)
        self.nighttime_label = with_bg(
            MDLabel(text="Night (auto): 30%", theme_text_color="Custom", text_color=TEXT_DARK)
        )
        ratio_row.add_widget(self.ratio_btn)
        ratio_row.add_widget(self.nighttime_label)
        form.add_widget(ratio_row)

        next_btn = MDRaisedButton(
            text="Next: Consumption", size_hint_x=1, md_bg_color=ACCENT, text_color=WHITE,
            on_release=lambda *_: self._go_next(),
        )
        form.add_widget(next_btn)

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _open_ratio_menu(self, *_args) -> None:
        items = [
            {"text": ratio, "on_release": lambda r=ratio: self._select_ratio(r)}
            for ratio in DAY_NIGHT_RATIOS
        ]
        self._ratio_menu = MDDropdownMenu(caller=self.ratio_btn, items=items, width_mult=3)
        self._ratio_menu.open()

    def _select_ratio(self, ratio: str) -> None:
        self._daytime_pct = int(ratio.split("/")[0])
        self.ratio_btn.text = f"Ratio: {ratio}"
        self.nighttime_label.text = f"Night (auto): {100 - self._daytime_pct}%"
        if self._ratio_menu:
            self._ratio_menu.dismiss()

    def _open_country_menu(self, *_args) -> None:
        items = [
            {"text": country, "on_release": lambda c=country: self._select_country(c)}
            for country in sorted(COUNTRY_LATITUDES.keys())
        ]
        self._country_menu = MDDropdownMenu(caller=self.country_btn, items=items, width_mult=4, max_height=dp(360))
        self._country_menu.open()

    def _select_country(self, country: str) -> None:
        self._country = country
        self.country_btn.text = country
        if self._country_menu:
            self._country_menu.dismiss()

    def _open_project_menu(self, *_args) -> None:
        items = [{"text": "(Unsaved new project)", "on_release": lambda: self._select_project(None)}]
        for row in database.list_projects():
            label = f"{row['client_name'] or '(Untitled)'} - {row['project_date']}"
            items.append({"text": label, "on_release": lambda pid=row["id"]: self._select_project(pid)})
        self._project_menu = MDDropdownMenu(caller=self.project_btn, items=items, width_mult=4)
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
        self.ratio_btn.text = f"Ratio: {project.daytime_ratio_pct}/{project.nighttime_ratio_pct}"
        self.nighttime_label.text = f"Night (auto): {project.nighttime_ratio_pct}%"
        self.electricity_rate_field.text = f"{project.electricity_rate:.2f}"
        self._country = project.country
        self.country_btn.text = project.country or "Select Country"
        self.current_project_id = project.id

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
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _refresh_project_list(self) -> None:
        pass  # project list is fetched fresh each time the dropdown opens

    def _new_project(self) -> None:
        self._apply_project(Project(daytime_ratio_pct=70, electricity_rate=DEFAULT_ELECTRICITY_RATE))
        self.project_btn.text = "(Unsaved new project)"

    def _save_project(self) -> None:
        try:
            project = self._collect_project()
        except ValueError:
            self._show_message("Invalid Data", "Please enter valid numbers.")
            return
        error = self._validate(project)
        if error:
            self._show_message("Invalid Data", error)
            return

        if self.current_project_id is None:
            self.current_project_id = database.create_project(project.to_fields())
        else:
            database.update_project(self.current_project_id, project.to_fields())

        row = database.get_project(self.current_project_id)
        self.project_btn.text = f"{row['client_name']} - {row['project_date']}"
        self._show_message("Saved", f"Project saved for {project.client_name}.")

    def _duplicate_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Save the current project before duplicating it.")
            return
        new_id = database.duplicate_project(self.current_project_id)
        row = database.get_project(new_id)
        self._apply_project(Project.from_row(row))
        self.project_btn.text = f"{row['client_name']} - {row['project_date']}"

    def _delete_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Select a saved project to delete.")
            return
        database.delete_project(self.current_project_id)
        self._new_project()

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
