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
import logging
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from copy import deepcopy

from kivy.metrics import dp
from kivy.clock import Clock
from kivy.utils import platform
from kivymd.uix.textfield import MDTextField
from kivymd.uix.selectioncontrol import MDCheckbox
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from db import database
from logic.models import Project
from logic.quote_validation import validate_quote_steps
from ui_style import (
    ON_SURFACE_VARIANT, about_button, bottom_primary_action, header_actions, keep_focused_field_visible, m3_field, picker_field, primary_button, save_button, save_current_project,
    project_row, screen_header, section_card, show_paywall,
)

DAY_NIGHT_RATIOS = ["10/90", "20/80", "30/70", "40/60", "50/50", "60/40", "70/30", "80/20", "90/10"]
DEFAULT_ELECTRICITY_RATE = 14.50
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The other 6 wizard steps, in the order their state is nested under a saved
# project's quote_data JSON blob -- Client Info itself is already covered by
# the project's own plain columns, so it isn't included here.
QUOTE_STEP_SCREENS = ["consumption", "solar", "battery", "system_design", "simulation", "roi"]
log = logging.getLogger(__name__)


def project_today() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def restore_quote_steps(app, quote_data: dict) -> None:
    """Refresh each step's inputs before restoring its saved editable values.

    Later steps read derived values from earlier steps through app.state, so
    restoring only the widgets would mix two different projects' calculations.
    """
    for name in QUOTE_STEP_SCREENS:
        screen = app.root.get_screen(name)
        saved = quote_data.get(name, {})
        if not isinstance(saved, dict):
            log.warning("Ignoring malformed saved state for %s", name)
            saved = {}
        screen.on_pre_enter()
        try:
            screen.apply_state(saved)
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            log.warning("Could not restore saved state for %s: %s", name, exc)
            screen.apply_state({})
        finally:
            if name == "simulation":
                screen.on_leave()  # on_pre_enter starts its animated background


class ClientScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "client"
        self.current_project_id: int | None = None
        self._daytime_pct = 70
        # Fixed: SolarQuote is Philippines-only, so this is never reassigned
        # by the UI (see the country_field construction in _build_ui).
        self._country = "Philippines"
        self._dialog: MDDialog | None = None
        self._project_menu: MDDropdownMenu | None = None
        self._overflow_menu: MDDropdownMenu | None = None
        self._ratio_menu: MDDropdownMenu | None = None
        self._saved_snapshot = None
        self._suspend_draft = False
        self._last_draft = None
        self._site_fetching = False

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
            on_switch=self._open_project_menu, on_new=lambda: self._guard_unsaved(self._new_project),
            on_more=self._open_overflow_menu,
        )
        form.add_widget(self.project_row_widget)

        client_card = section_card("card-account-details-outline", "Client Details")
        self.client_name_field = m3_field("Client Name *", icon="account")
        self.project_location_field = m3_field("Project Location", icon="map-marker")
        client_card.add_widget(self.client_name_field)
        client_card.add_widget(self.project_location_field)

        # Fixed, non-editable: SolarQuote is scoped to Philippines-only for now
        # (electricity rates, currency, and every financial figure in the app
        # are PHP-denominated with no per-country switching), so letting users
        # pick a different country here would be misleading rather than useful.
        self.country_field = m3_field("Country", icon="earth", text="Philippines", disabled=True)
        client_card.add_widget(self.country_field)
        client_card.add_widget(MDLabel(
            text="SolarQuote is currently available for the Philippines only.",
            font_style="Caption", theme_text_color="Custom", text_color=ON_SURFACE_VARIANT,
            size_hint_y=None, height=dp(16),
        ))

        contact_date_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(52))
        self.contact_number_field = m3_field("Contact No.", icon="phone")
        self.date_field = m3_field("Date", icon="calendar", text=project_today())
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

        design_card = section_card("flash-outline", "Automatic Design")
        self.peak_load_field = m3_field("Measured simultaneous demand (kW, optional)", input_filter="float")
        self.surge_load_field = m3_field("Appliance startup demand (kW, optional)", input_filter="float")
        design_card.add_widget(self.peak_load_field)
        design_card.add_widget(self.surge_load_field)
        storage_row = MDBoxLayout(size_hint_y=None, height=dp(48))
        self.storage_checkbox = MDCheckbox(active=True, size_hint_x=None, width=dp(48))
        storage_row.add_widget(self.storage_checkbox)
        storage_row.add_widget(MDLabel(text="Include automatic battery storage"))
        design_card.add_widget(storage_row)
        design_card.add_widget(MDLabel(text="Leave demand blank for an estimated selection. Inverter, battery modules and voltage are selected automatically.",
                                       font_style="Caption", size_hint_y=None, height=dp(48)))
        form.add_widget(design_card)

        site_card = section_card("map-marker", "Optional Solar Resource")
        self.latitude_field = m3_field("Site latitude (-90 to 90)")
        self.longitude_field = m3_field("Site longitude (-180 to 180)")
        self.tilt_field = m3_field("Roof tilt (degrees)", text="10", input_filter="float")
        self.azimuth_field = m3_field("Roof azimuth (degrees, north = 0)", text="180", input_filter="float")
        self.shading_field = m3_field("Estimated shading loss %", text="0", input_filter="float")
        for field in (self.latitude_field, self.longitude_field, self.tilt_field, self.azimuth_field, self.shading_field):
            site_card.add_widget(field)
        from ui_style import tonal_button
        site_card.add_widget(tonal_button("Load site solar resource", on_release=self._load_site_resource))
        self.resource_label = MDLabel(text="Offline estimate until a measured or site resource is supplied. Loading sends coordinates only to NASA POWER; no client/contact data.",
                                      font_style="Caption", size_hint_y=None, height=dp(64))
        site_card.add_widget(self.resource_label)
        form.add_widget(site_card)

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
        self._guard_unsaved(lambda: self._load_project(project_id))

    def _load_project(self, project_id: int | None) -> None:
        if project_id is None:
            self._new_project()
            return
        row = database.get_project(project_id)
        if row is not None:
            self._apply_project(Project.from_row(row))
            self._apply_quote_data(row["quote_data"])
            self._mark_clean()

    def _open_overflow_menu(self) -> None:
        items = [
            {"text": "Duplicate", "on_release": lambda: self._overflow_action(self._duplicate_project)},
            {"text": "Delete", "on_release": lambda: self._overflow_action(self._delete_project)},
            {"text": "Export project backup", "on_release": lambda: self._overflow_action(self._export_backup)},
            {"text": "Import project backup", "on_release": lambda: self._overflow_action(self._import_backup)},
        ]
        self._overflow_menu = MDDropdownMenu(caller=self.project_row_widget, items=items, width_mult=3)
        self._overflow_menu.open()

    def _overflow_action(self, action) -> None:
        if self._overflow_menu:
            self._overflow_menu.dismiss()
        action()

    def _collect_project(self) -> Project:
        def optional(field):
            return float(field.text) if field.text.strip() else None
        return Project(
            id=self.current_project_id,
            client_name=self.client_name_field.text.strip(),
            project_location=self.project_location_field.text.strip(),
            contact_number=self.contact_number_field.text.strip(),
            email=self.email_field.text.strip(),
            project_date=self.date_field.text.strip(),
            notes=getattr(MDApp.get_running_app().state.project, "notes", ""),
            monthly_kwh=float(self.monthly_kwh_field.text or 0),
            daytime_ratio_pct=self._daytime_pct,
            electricity_rate=float(self.electricity_rate_field.text or 0),
            country=self._country,
            peak_load_kw=optional(self.peak_load_field), surge_load_kw=optional(self.surge_load_field),
            storage_enabled=self.storage_checkbox.active,
            site_latitude=optional(self.latitude_field), site_longitude=optional(self.longitude_field),
            site_tilt_deg=float(self.tilt_field.text or 0), site_azimuth_deg=float(self.azimuth_field.text or 0),
            site_shading_pct=float(self.shading_field.text or 0),
        )

    def _apply_project(self, project: Project) -> None:
        self.client_name_field.text = project.client_name
        self.project_location_field.text = project.project_location
        self.contact_number_field.text = project.contact_number
        self.email_field.text = project.email
        self.date_field.text = project.project_date or project_today()
        self.monthly_kwh_field.text = f"{project.monthly_kwh:.2f}"
        self._daytime_pct = project.daytime_ratio_pct
        self.ratio_field.set_value(f"{project.daytime_ratio_pct}% / {project.nighttime_ratio_pct}%")
        self.electricity_rate_field.text = f"{project.electricity_rate:.2f}"
        # self._country stays "Philippines" regardless of what an older saved
        # project recorded -- the country field is fixed now, not restored.
        self.current_project_id = project.id
        for field, value in ((self.peak_load_field, project.peak_load_kw), (self.surge_load_field, project.surge_load_kw),
                             (self.latitude_field, project.site_latitude), (self.longitude_field, project.site_longitude),
                             (self.tilt_field, project.site_tilt_deg), (self.azimuth_field, project.site_azimuth_deg),
                             (self.shading_field, project.site_shading_pct)):
            field.text = str(value) if value is not None else ""
        self.storage_checkbox.active = project.storage_enabled
        MDApp.get_running_app().state.project = project
        self._sync_design_inputs(project)
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
            "notes": project.notes,
            "monthly_kwh": project.monthly_kwh,
            "daytime_pct": project.daytime_ratio_pct,
            "nighttime_pct": project.nighttime_ratio_pct,
            "electricity_rate": project.electricity_rate,
            "country": project.country,
            **project.design_inputs(),
        }

    def _validate(self, project: Project) -> str | None:
        if not project.client_name:
            return "Client Name is required."
        if not math.isfinite(project.monthly_kwh) or project.monthly_kwh <= 0:
            return "Latest Monthly Electricity Consumption must be greater than 0."
        if not math.isfinite(project.electricity_rate) or project.electricity_rate < 0:
            return "Electricity Rate must be a non-negative number."
        if project.monthly_kwh > 1e9 or project.electricity_rate > 1e6:
            return "Consumption or tariff exceeds the supported range."
        if not 0 <= project.daytime_ratio_pct <= 100:
            return "Daytime percentage must be between 0 and 100."
        for name in ("peak_load_kw", "surge_load_kw"):
            value = getattr(project, name)
            if value is not None and (not math.isfinite(value) or not 0 < value <= 10000):
                return "Measured peak and startup demand must be finite positive kW values."
        if project.peak_load_kw is not None and project.surge_load_kw is not None and project.surge_load_kw < project.peak_load_kw:
            return "Startup demand must be at least the simultaneous demand."
        if (project.site_latitude is None) != (project.site_longitude is None):
            return "Enter both site latitude and longitude."
        for name, low, high in (("site_latitude", -90, 90), ("site_longitude", -180, 180),
                                 ("site_tilt_deg", 0, 90), ("site_azimuth_deg", 0, 360), ("site_shading_pct", 0, 100)):
            value = getattr(project, name)
            if value is not None and (not math.isfinite(value) or not low <= value <= high):
                return f"{name.replace('_', ' ').title()} is out of range."
        if project.project_date:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", project.project_date):
                    return "Date must be in YYYY-MM-DD format."
                date.fromisoformat(project.project_date)
            except ValueError:
                return "Date must be in YYYY-MM-DD format."
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
        app = MDApp.get_running_app()
        if app.root is not None and app.root.has_screen("roi"):
            self._apply_quote_data("{}")
        self._mark_clean()

    def _apply_quote_data(self, quote_data_json: str) -> None:
        """Restores Consumption through Savings & ROI's editable fields from a
        saved project's quote_data JSON blob (empty/legacy rows -- '{}' -- just
        reset every step to its own defaults, same as a brand new project)."""
        try:
            quote_data = json.loads(quote_data_json) if quote_data_json else {}
        except (TypeError, ValueError):
            log.warning("Saved quote contains invalid JSON; restoring defaults")
            quote_data = {}
        if not isinstance(quote_data, dict):
            log.warning("Saved quote is not an object; restoring defaults")
            quote_data = {}
        app = MDApp.get_running_app()
        restore_quote_steps(app, quote_data)
        if app.root.has_screen("report") and hasattr(app.root.get_screen("report"), "apply_state"):
            app.root.get_screen("report").apply_state(quote_data.get("report", {}))

    def _collect_quote_data(self) -> dict:
        app = MDApp.get_running_app()
        data = {name: app.root.get_screen(name).collect_state() for name in QUOTE_STEP_SCREENS}
        if app.root.has_screen("report") and hasattr(app.root.get_screen("report"), "collect_state"):
            data["report"] = app.root.get_screen("report").collect_state()
        return data

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

        app = MDApp.get_running_app()
        app.state.project = project
        self._sync_design_inputs(project)
        for name in QUOTE_STEP_SCREENS:
            screen = app.root.get_screen(name)
            screen.on_pre_enter()
            if name == "simulation" and app.root.current != name:
                screen.on_leave()
        quote_data = self._collect_quote_data()
        error = validate_quote_steps(quote_data)
        if error:
            self._show_message("Invalid Data", error)
            return False
        fields = project.to_fields()
        fields["quote_data"] = json.dumps(quote_data)
        try:
            if self.current_project_id is None:
                if database.get_tier() == "free" and database.count_projects() >= database.FREE_PROJECT_LIMIT:
                    show_paywall(
                        self,
                        reason=(
                            f"Free tier limited to {database.FREE_PROJECT_LIMIT} saved projects. "
                            "Delete an old one from the project list to keep going without upgrading."
                        ),
                    )
                    return False
                self.current_project_id = database.create_project(fields)
                project.id = self.current_project_id
            else:
                database.update_project(self.current_project_id, fields)
            row = database.get_project(self.current_project_id)
        except (sqlite3.Error, OSError, LookupError):
            log.exception("Could not save project")
            self._show_message("Save Failed", "Could not save this project. Please check available storage and try again.")
            return False
        self.project_row_widget._value_label.text = f"{row['client_name']} - {row['project_date']}"
        self._mark_clean()
        self.persist_draft()
        return True

    def _duplicate_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Save the current project before duplicating it.")
            return
        if database.get_tier() == "free" and database.count_projects() >= database.FREE_PROJECT_LIMIT:
            show_paywall(
                self,
                reason=(
                    f"Free tier limited to {database.FREE_PROJECT_LIMIT} saved projects. "
                    "Delete an old one from the project list to keep going without upgrading."
                ),
            )
            return
        if not self.save_full_quote():
            return
        try:
            new_id = database.duplicate_project(self.current_project_id)
            row = database.get_project(new_id)
        except (sqlite3.Error, OSError, LookupError, TypeError):
            log.exception("Could not duplicate project")
            self._show_message("Duplicate Failed", "Could not duplicate this project.")
            return
        self._apply_project(Project.from_row(row))
        self._apply_quote_data(row["quote_data"])
        self.project_row_widget._value_label.text = f"{row['client_name']} - {row['project_date']}"
        self._mark_clean()

    def _delete_project(self) -> None:
        if self.current_project_id is None:
            self._show_message("No Project", "Select a saved project to delete.")
            return
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title="Delete Project?",
            text="This saved project and its full quote will be permanently deleted.",
            buttons=[
                primary_button("Cancel", on_release=lambda: self._dialog.dismiss(),
                               size_hint_x=None, width=dp(90)),
                primary_button("Delete", on_release=self._confirm_delete_project,
                               size_hint_x=None, width=dp(90)),
            ],
        )
        self._dialog.open()

    def _confirm_delete_project(self) -> None:
        if self._dialog:
            self._dialog.dismiss()
        try:
            database.delete_project(self.current_project_id)
        except (sqlite3.Error, OSError):
            log.exception("Could not delete project")
            self._show_message("Delete Failed", "Could not delete this project.")
            return
        self._new_project()

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"

    def _sync_design_inputs(self, project: Project) -> None:
        state = MDApp.get_running_app().state
        for name, value in project.design_inputs().items():
            setattr(state, name, value)

    def capture_snapshot(self) -> dict:
        app = MDApp.get_running_app()
        screens = {"client": self}
        if app.root is not None:
            for name in QUOTE_STEP_SCREENS + ["report"]:
                if app.root.has_screen(name):
                    screens[name] = app.root.get_screen(name)
        raw = {}
        for name, screen in screens.items():
            values = {}
            for key, value in vars(screen).items():
                if isinstance(value, MDTextField):
                    values[key] = value.text
                elif isinstance(value, dict) and value and all(isinstance(item, MDTextField) for item in value.values()):
                    values[key] = {subkey: item.text for subkey, item in value.items()}
                elif isinstance(value, list) and value and all(isinstance(item, MDTextField) for item in value):
                    values[key] = [item.text for item in value]
            raw[name] = values
        steps = {}
        for name, screen in screens.items():
            if hasattr(screen, "collect_state"):
                try:
                    steps[name] = _json_safe(screen.collect_state())
                except (TypeError, ValueError, OverflowError):
                    steps[name] = {}
        return {"raw_fields": raw, "quote_state": steps, "project_id": self.current_project_id,
                "daytime_pct": self._daytime_pct, "storage_enabled": self.storage_checkbox.active}

    def _mark_clean(self) -> None:
        self._saved_snapshot = deepcopy(self.capture_snapshot())

    def persist_draft(self, *_args) -> None:
        if self._suspend_draft:
            return
        snapshot = self.capture_snapshot()
        if snapshot != self._last_draft:
            try:
                database.save_draft(snapshot)
                self._last_draft = deepcopy(snapshot)
            except (ValueError, sqlite3.Error, OSError):
                log.exception("Could not preserve draft")

    def restore_draft(self) -> bool:
        data = database.load_draft()
        if not data or not isinstance(data.get("raw_fields"), dict):
            self._mark_clean()
            return False
        self._suspend_draft = True
        try:
            pid = data.get("project_id")
            if isinstance(pid, int) and database.get_project(pid) is not None:
                self._load_project(pid)
            else:
                self._new_project()
            self._daytime_pct = data.get("daytime_pct", 70)
            self.ratio_field.set_value(f"{self._daytime_pct}% / {100 - self._daytime_pct}%")
            self.storage_checkbox.active = bool(data.get("storage_enabled", True))
            client_raw = data["raw_fields"].get("client", {})
            for key, text in client_raw.items():
                field = getattr(self, key, None)
                if isinstance(field, MDTextField) and isinstance(text, str):
                    field.text = text
            try:
                project = self._collect_project()
                if self._validate(project) is None:
                    MDApp.get_running_app().state.project = project
                    self._sync_design_inputs(project)
            except (ValueError, TypeError):
                pass  # raw incomplete fields remain recoverable
            self._apply_quote_data(json.dumps(data.get("quote_state", {})))
            app = MDApp.get_running_app()
            for name, values in data["raw_fields"].items():
                if not app.root.has_screen(name) or not isinstance(values, dict):
                    continue
                screen = app.root.get_screen(name)
                for key, saved in values.items():
                    field = getattr(screen, key, None)
                    if isinstance(field, MDTextField) and isinstance(saved, str):
                        field.text = saved
                    elif isinstance(field, dict) and isinstance(saved, dict):
                        for subkey, text in saved.items():
                            if isinstance(field.get(subkey), MDTextField) and isinstance(text, str):
                                field[subkey].text = text
                    elif isinstance(field, list) and isinstance(saved, list) and len(field) == len(saved):
                        for item, text in zip(field, saved):
                            if isinstance(item, MDTextField) and isinstance(text, str):
                                item.text = text
            self._last_draft = self.capture_snapshot()
            self.project_row_widget._value_label.text += " (draft recovered)"
            return True
        except (TypeError, ValueError, KeyError, OverflowError):
            log.exception("Could not restore draft")
            return False
        finally:
            self._suspend_draft = False

    def _guard_unsaved(self, action) -> None:
        if self._saved_snapshot is None or self.capture_snapshot() == self._saved_snapshot:
            action()
            return
        from kivymd.uix.button import MDFlatButton
        if self._dialog:
            self._dialog.dismiss()
        def discard(*_args):
            self._dialog.dismiss()
            action()
            self.persist_draft()
        def save(*_args):
            self._dialog.dismiss()
            if self.save_full_quote():
                action()
                self.persist_draft()
        self._dialog = MDDialog(title="Unsaved changes", text="Save this quote before replacing the current draft?",
                                buttons=[MDFlatButton(text="CANCEL", on_release=lambda *_: self._dialog.dismiss()),
                                         MDFlatButton(text="DISCARD", on_release=discard),
                                         MDFlatButton(text="SAVE", on_release=save)])
        self._dialog.open()

    def _export_backup(self) -> None:
        app = MDApp.get_running_app()
        path = str(Path(app.user_data_dir) / "project-backups" / f"SolarQuote-projects-{project_today()}.json")
        try:
            database.export_projects(path)
            report = app.root.get_screen("report")
            if hasattr(report, "_save_as"):
                report._save_as(path, "application/json")
            else:
                self._show_message("Backup saved", path)
        except (OSError, ValueError, sqlite3.Error):
            log.exception("Project backup failed")
            self._show_message("Backup failed", "Could not export the saved projects.")

    def _import_backup(self) -> None:
        if platform == "android":
            app = MDApp.get_running_app()
            app.root.get_screen("report").choose_import_file(self._import_android_backup)
            return
        from plyer import filechooser
        try:
            filechooser.open_file(on_selection=lambda selected: Clock.schedule_once(lambda _dt: self._import_backup_path(selected)))
        except (NotImplementedError, OSError):
            self._show_message("Import unavailable", "Your device does not provide a document picker.")

    def _import_android_backup(self, path) -> None:
        if not path:
            return
        try:
            self._import_backup_path([path])
        finally:
            Path(path).unlink(missing_ok=True)

    def _import_backup_path(self, selected) -> None:
        if not selected:
            return
        try:
            slots = max(0, database.FREE_PROJECT_LIMIT - database.count_projects()) if database.get_tier() == "free" else None
            ids = database.import_projects(selected[0], max_new_projects=slots)
            self._show_message("Backup imported", f"Imported {len(ids)} projects. Existing projects were kept.")
        except (OSError, ValueError, sqlite3.Error, TypeError) as exc:
            self._show_message("Import failed", str(exc))

    def _load_site_resource(self) -> None:
        if self._site_fetching:
            return
        try:
            latitude = float(self.latitude_field.text)
            longitude = float(self.longitude_field.text)
            tilt = float(self.tilt_field.text or 0)
            azimuth = float(self.azimuth_field.text or 0)
            shading = float(self.shading_field.text or 0)
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError
        except ValueError:
            self._show_message("Site coordinates", "Enter a valid latitude and longitude to load a local solar resource.")
            return
        self._site_fetching = True
        self.resource_label.text = "Loading solar resource for these coordinates…"
        app = MDApp.get_running_app()
        def fetch():
            from logic.site_resources import load_solar_resource
            try:
                resource = load_solar_resource(latitude, longitude, str(Path(app.user_data_dir) / "solar-resources"), tilt=tilt, azimuth=azimuth, shading_pct=shading)
                Clock.schedule_once(lambda _dt: apply_resource(resource))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                message = str(exc)
                Clock.schedule_once(lambda _dt: fail(message))
        def apply_resource(resource):
            self._site_fetching = False
            try:
                unchanged = (float(self.latitude_field.text), float(self.longitude_field.text),
                             float(self.tilt_field.text), float(self.azimuth_field.text), float(self.shading_field.text)) == (latitude, longitude, tilt, azimuth, shading)
            except ValueError:
                unchanged = False
            if not unchanged:
                self.resource_label.text = "Site changed during loading. Reload the resource for the new site."
                return
            solar = app.root.get_screen("solar")
            solar.set_resource_data(resource, coordinates=(latitude, longitude))
            self.resource_label.text = f"{resource['source']}: {resource['annual_peak_sun_hours']:.2f} average sun hours. Monthly roof/shading estimate; cached for offline use."
            self.persist_draft()
        def fail(message):
            self._site_fetching = False
            self.resource_label.text = "Resource unavailable. Offline assumptions retained. " + message
        Thread(target=fetch, daemon=True).start()

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
        self._sync_design_inputs(project)
        app.root.current = "consumption"
