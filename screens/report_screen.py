"""Proposal preview, scheduled GPU capture, background export, and user-directed copies.

Reports remain in app-managed storage until the user chooses Save a Copy, Share,
or Email. History exposes prior reports without relying on a device file manager.
"""

import os
import shutil
import logging
import copy
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.spinner import MDSpinner

from db import database
from logic.chart_series import DOD_FLOOR_COLOR, roi_chart_series, series_for_result
from logic.reports import DISCLAIMER, SCENARIO_ORDER, generate_atomic, proposal_metadata
from logic.quote_validation import validate_quote_steps
from ui_style import (
    ACCENT, APP_VERSION, TEXT_DARK, about_button, bottom_back_action, header_actions, icon_button, keep_focused_field_visible, m3_field, save_button,
    screen_header, section_card, section_label, show_paywall, tonal_button, with_bg,
)
from widgets.line_chart import LineChart

MIME_TYPES = {
    "pdf": "application/pdf",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
log = logging.getLogger(__name__)


def launch_android_intent(activity, intent, request_code=None, on_error=None):
    """Android Activity launches must run on Android's UI thread, separate from Kivy."""
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def launch():
        try:
            if request_code is None:
                activity.startActivity(intent)
            else:
                activity.startActivityForResult(intent, request_code)
        except Exception:
            log.warning("Android document activity could not be opened")
            if on_error:
                Clock.schedule_once(lambda _dt: on_error(), 0)

    launch()


def available_export_path(directory: str, filename: str) -> str:
    """Keep prior proposals when the user exports the same format again."""
    stem, extension = os.path.splitext(filename)
    path = os.path.join(directory, filename)
    number = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{number}{extension}")
        number += 1
    return path


def export_success_text(path: str, on_android: bool) -> str:
    """Describe the exported file without displaying app-private storage paths."""
    message = f"Saved as {os.path.basename(path)}"
    if on_android:
        message += "\nUse View or Share to access the report, or Save a copy to keep it outside the app."
    else:
        message += f"\nFolder: {os.path.dirname(path)}"
    return message


def report_filename(data: dict, kind: str) -> str:
    name = re.sub(r"[^\w-]+", "_", data["client"].get("client_name", "client"), flags=re.UNICODE).strip("_")[:50] or "client"
    identifier = dict(proposal_metadata(data))["Quote ID"]
    extension = {"pdf": "pdf", "excel": "xlsx", "csv": "csv", "pptx": "pptx"}[kind]
    date = re.sub(r"[^0-9-]", "", data["client"].get("project_date", ""))[:10]
    return f"{identifier}_{name}_{date}.{extension}"


def list_exported_reports(directory: str) -> list:
    folder = Path(directory)
    if not folder.is_dir():
        return []
    return sorted((item for item in folder.iterdir() if item.is_file()
                   and item.suffix.lower() in {".pdf", ".xlsx", ".csv", ".pptx"}
                   and (item.name.startswith("SQ-") or item.name.startswith("solar_proposal"))),
                  key=lambda item: item.stat().st_mtime, reverse=True)


def copy_document_stream(stream, path, max_bytes=20 * 1024 * 1024):
    """Copy a Java InputStream with bounded memory/size; remove incomplete copies."""
    buffer = bytearray(65536)
    total = 0
    try:
        with open(path, "wb") as destination:
            while True:
                count = stream.read(buffer)
                if count == -1:
                    break
                if not 0 < count <= len(buffer):
                    raise OSError("Document provider returned no data")
                total += count
                if total > max_bytes:
                    raise ValueError("Backup exceeds 20 MB")
                destination.write(buffer[:count])
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return str(path)

# Must exactly match p4a_hooks.py's FILEPROVIDER_AUTHORITY (package.domain +
# "." + package.name + ".fileprovider" from buildozer.spec).
FILEPROVIDER_AUTHORITY = "org.solarclientfinder.solarclientfinder.fileprovider"


def export_dir(app) -> str:
    """App-managed report storage; Save a Copy uses the system document picker."""
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Environment = autoclass("android.os.Environment")
            context = PythonActivity.mActivity
            ext_dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            if ext_dir is not None:
                return ext_dir.getAbsolutePath()
        except Exception:
            pass
    return os.path.join(app.user_data_dir, "reports")


class ReportScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "report"
        self._dialog: MDDialog | None = None
        self._spinner_overlay = None
        self._exporting = False
        self._save_request = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        self._content_root = root
        root.add_widget(screen_header(
            "Report", step=8, on_back=self._go_back,
            right_widget=header_actions(
                about_button(self._go_about),
                icon_button("home-outline", on_release=self._go_home, color=ACCENT),
                save_button(on_release=self._save_project),
            ),
        ))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(16), padding=dp(16), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        branding_card = section_card("briefcase-outline", "Report Branding")
        self.company_name_field = m3_field("Company Name (optional)", icon="office-building-outline")
        branding_card.add_widget(self.company_name_field)
        form.add_widget(branding_card)

        preview_card = section_card("file-document-edit-outline", "Report Preview")
        preview_card.add_widget(tonal_button("Refresh Preview", on_release=self._refresh_preview))
        self.preview_label = with_bg(MDLabel(
            text="Tap Refresh Preview to see a summary.", theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None,
        ))
        self.preview_label.bind(texture_size=lambda _i, val: setattr(self.preview_label, "height",
                                                                       max(dp(80), val[1] + dp(16))))
        self.preview_label.bind(width=lambda _i, val: setattr(self.preview_label, "text_size", (val - dp(16), None)))
        preview_card.add_widget(self.preview_label)
        form.add_widget(preview_card)

        export_card = section_card("printer-outline", "Export")
        export_grid = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        export_grid.bind(minimum_height=export_grid.setter("height"))
        export_grid.bind(width=lambda widget, width: setattr(widget, "cols", 2 if width >= dp(580) else 1))
        for label, kind in (("EXPORT PDF", "pdf"), ("EXPORT EXCEL", "excel"), ("EXPORT CSV", "csv"), ("EXPORT POWERPOINT", "pptx")):
            button = tonal_button(label, on_release=lambda selected=kind: self._export(selected), size_hint_x=None)
            cell = AnchorLayout(size_hint_y=None, height=dp(44))
            cell.bind(width=lambda widget, width, action=button: setattr(action, "width", width))
            cell.add_widget(button)
            export_grid.add_widget(cell)
        export_card.add_widget(export_grid)
        history_button = tonal_button("REPORT HISTORY", on_release=self._show_history, size_hint_x=None)
        history_cell = AnchorLayout(size_hint_y=None, height=dp(44))
        history_cell.bind(width=lambda widget, width: setattr(history_button, "width", width))
        history_cell.add_widget(history_button)
        export_card.add_widget(history_cell)
        form.add_widget(export_card)

        form.add_widget(section_label("information-outline", "Disclaimer"))
        disclaimer_label = MDLabel(
            text=DISCLAIMER, theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None,
        )
        disclaimer_label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        disclaimer_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp(12)))
        form.add_widget(disclaimer_label)
        form.add_widget(bottom_back_action(self._go_back))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _collect_data(self) -> dict:
        app = MDApp.get_running_app()
        sm = app.root
        data = {
            "company_name": self.company_name_field.text.strip(),
            "client": sm.get_screen("client").get_report_data(),
            "consumption": sm.get_screen("consumption").get_report_data(),
            "solar": sm.get_screen("solar").get_report_data(),
            "battery": sm.get_screen("battery").get_report_data(),
            "system_design": sm.get_screen("system_design").get_report_data(),
            "simulation": sm.get_screen("simulation").get_report_data(),
            "roi": sm.get_screen("roi").get_report_data(),
            "assumptions": {name: sm.get_screen(name).collect_state() for name in
                            ("consumption", "solar", "battery", "system_design", "simulation", "roi")},
            "created_with_version": APP_VERSION,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        data["assumptions"]["client"] = dict(data["client"])
        design = getattr(app.state, "design", None)
        if design is not None and hasattr(design, "as_dict"):
            data["equipment_design"] = design.as_dict()
        data["quote_id"] = dict(proposal_metadata(data))["Quote ID"]
        return data

    def collect_state(self) -> dict:
        return {"company_name": self.company_name_field.text.strip()}

    def apply_state(self, data: dict) -> None:
        data = data if isinstance(data, dict) else {}
        company = data.get("company_name", "")
        self.company_name_field.text = company if isinstance(company, str) else ""
        self.preview_label.text = "Preview will refresh when you open the report."

    def on_pre_enter(self, *_args) -> None:
        try:
            self._refresh_preview()
        except (ValueError, TypeError, KeyError):
            self.preview_label.text = "Complete the quote inputs to preview the current project."

    def _refresh_preview(self) -> None:
        data = self._collect_data()
        client = data["client"]
        solar = data["solar"]
        battery = data["battery"]
        system_design = data["system_design"]
        roi = data["roi"]

        title = data["company_name"] or "Solar Proposal"
        payback = f"{roi['payback_years']:.1f} years" if roi["payback_years"] is not None else "Not within horizon"
        lines = [
            title,
            f"Client: {client['client_name'] or '-'}",
            f"Location: {client['project_location'] or '-'}",
            f"Monthly Consumption: {client['monthly_kwh']:.2f} kWh "
            f"({client['daytime_pct']}% day / {client['nighttime_pct']}% night)",
            "",
            "Recommended System",
            f"Solar: {solar['total_kw']:.2f} kWp",
            f"Battery: {battery['total_kwh']:.2f} kWh (usable {battery['usable_kwh']:.2f} kWh)",
            f"Inverter: {system_design['rated_power_kw']:.2f} kW",
            "",
            "Financials",
            f"Estimated Monthly Savings: PHP {roi['monthly_savings']:,.2f}",
            f"Estimated Annual Savings: PHP {roi['annual_savings']:,.2f}",
            f"Estimated Payback Period: {payback}",
            f"{len(roi['projection_rows'])}-Year Net Benefit: PHP {roi['net_benefit']:,.2f}",
            "",
            "Engineering Notes",
        ]
        for ok, text in system_design["warnings"]:
            mark = "[OK]" if ok else "[!]"
            lines.append(f"{mark} {text}")

        self.preview_label.text = "\n".join(lines)

    def _chart_tmp_dir(self) -> str:
        if getattr(self, "_job_tmp_dir", None):
            return self._job_tmp_dir
        app = MDApp.get_running_app()
        return tempfile.mkdtemp(prefix="charts-", dir=app.user_data_dir)

    def _save_chart_png(self, chart: LineChart, image_path: str, label: str) -> str:
        """GPU capture on the UI thread; never recursively pump the event loop."""
        for child in chart.children:
            if hasattr(child, "texture_update"):
                child.texture_update()
        saved = chart.export_as_image().save(image_path, flipped=False)
        if not saved or not os.path.isfile(image_path):
            raise RuntimeError(f"Could not capture the {label} chart")
        return image_path

    def _chart_jobs(self, data, tmp_dir):
        roi = data["roi"]
        series, labels, vline = roi_chart_series(roi["system_cost"], roi["projection_rows"], roi["payback_years"])
        chart = LineChart(size_hint=(None, None), size=(1600, 700), text_scale=2.4)
        chart.set_data(series, labels, vline=vline, fill_index=0,
                       legend=["Cumulative cash flow"], x_unit="Years", y_unit="PHP")
        jobs = [("ROI", chart, os.path.join(tmp_dir, "roi.png"), "roi")]
        capacity = data["battery"]["total_kwh"]
        floor = capacity * (1 - data["battery"].get("dod_pct", 80) / 100)
        for name in SCENARIO_ORDER:
            result = data["simulation"]["scenario_results"].get(name)
            if result is None:
                continue
            series, labels, _hours = series_for_result(result, capacity)
            chart = LineChart(size_hint=(None, None), size=(1600, 700), text_scale=2.4)
            chart.set_data(series, labels, hline={"y": floor, "label": "DOD floor", "color": DOD_FLOOR_COLOR},
                           legend=["Consumption", "Solar", "Grid (+ export / - purchase)", "Stored battery"],
                           x_unit="Hour", y_unit="kWh")
            jobs.append((name, chart, os.path.join(tmp_dir, name.lower() + ".png"), name))
        return jobs

    def _render_roi_chart(self, data):
        return self._save_chart_png(*self._chart_jobs(data, self._chart_tmp_dir())[0][1:3], "ROI")

    def _render_scenario_charts(self, data):
        return {name: self._save_chart_png(chart, path, name)
                for name, chart, path, _key in self._chart_jobs(data, self._chart_tmp_dir())[1:]}

    def _cleanup_chart_images(self, paths):
        for folder in {str(Path(path).parent) for path in paths}:
            shutil.rmtree(folder, ignore_errors=True)

    def _export(self, kind: str) -> None:
        if self._exporting:
            return
        if database.get_tier() == "free" and kind != "pdf":
            show_paywall(self, reason="Upgrade to Pro to export Excel, CSV, and PowerPoint.")
            return
        self._exporting = True
        self._show_loading(f"Generating {kind.upper()} report...")
        Clock.schedule_once(lambda _dt: self._do_export(kind), 0)

    def _show_loading(self, text: str) -> None:
        self._dismiss_loading()
        self._content_root.disabled = True
        self._spinner_overlay = AnchorLayout(anchor_x="center", anchor_y="center")
        self._spinner_overlay.add_widget(MDSpinner(size_hint=(None, None), size=(dp(48), dp(48)), active=True, color=ACCENT))
        self.add_widget(self._spinner_overlay)

    def _dismiss_loading(self) -> None:
        if self._spinner_overlay and self._spinner_overlay.parent:
            self._spinner_overlay.parent.remove_widget(self._spinner_overlay)
        self._spinner_overlay = None
        self._content_root.disabled = False

    def _do_export(self, kind: str) -> None:
        try:
            app = MDApp.get_running_app()
            client = app.root.get_screen("client")
            error = client._validate(client._collect_project()) or validate_quote_steps(client._collect_quote_data())
            if error:
                raise ValueError(error)
            data = copy.deepcopy(self._collect_data())
            out_dir = export_dir(app)
            os.makedirs(out_dir, exist_ok=True)
            path = available_export_path(out_dir, report_filename(data, kind))
            self._job_tmp_dir = tempfile.mkdtemp(prefix="charts-", dir=app.user_data_dir)
            job = {"kind": kind, "data": data, "path": path, "tmp_dir": self._job_tmp_dir,
                   "watermark": "SolarQuote Free" if database.get_tier() == "free" else None,
                   "images": {}, "pending": []}
            if kind in ("pdf", "pptx"):
                job["pending"] = self._chart_jobs(data, job["tmp_dir"])
                Clock.schedule_once(lambda _dt: self._capture_next(job), 0.05)
            else:
                self._start_export_worker(job)
        except Exception as exc:
            self._exporting = False
            if getattr(self, "_job_tmp_dir", None):
                shutil.rmtree(self._job_tmp_dir, ignore_errors=True)
                self._job_tmp_dir = None
            log.exception("Could not prepare proposal")
            self._show_message("Export Failed", str(exc) if isinstance(exc, ValueError) else "Could not prepare the proposal. Check your entries and available storage.")

    def _capture_next(self, job, attempts=0):
        if not job["pending"]:
            self._start_export_worker(job)
            return
        name, chart, path, key = job["pending"][0]
        try:
            job["images"][key] = self._save_chart_png(chart, path, name)
        except Exception:
            if attempts < 4:
                Clock.schedule_once(lambda _dt: self._capture_next(job, attempts + 1), 0.05)
                return
            log.exception("Chart capture failed")
            self._finish_export(job, "Could not render a chart. Try exporting again.")
            return
        job["pending"].pop(0)
        Clock.schedule_once(lambda _dt: self._capture_next(job), 0)

    def _start_export_worker(self, job):
        def work():
            error = None
            try:
                from PIL import Image
                for path in job["images"].values():
                    with Image.open(path) as im:
                        flattened = Image.new("RGB", im.size, "white")
                        flattened.paste(im, mask=im.convert("RGBA").getchannel("A"))
                        flattened.save(path)
                generate_atomic(job["kind"], job["path"], job["data"],
                                roi_chart_image=job["images"].get("roi"),
                                scenario_images={key: value for key, value in job["images"].items() if key != "roi"},
                                watermark=job["watermark"])
            except Exception:
                log.exception("Proposal generation failed")
                error = "Could not generate the proposal. Check available storage and try again."
            finally:
                shutil.rmtree(job["tmp_dir"], ignore_errors=True)
            Clock.schedule_once(lambda _dt: self._finish_export(job, error), 0)
        threading.Thread(target=work, daemon=True, name="solarquote-export").start()

    def _finish_export(self, job, error):
        self._exporting = False
        self._job_tmp_dir = None
        shutil.rmtree(job["tmp_dir"], ignore_errors=True)
        if error:
            self._show_message("Export Failed", error)
        else:
            self._show_export_success(job["path"], MIME_TYPES[job["kind"]], job["data"]["client"].get("email", ""))

    def _show_message(self, title: str, text: str) -> None:
        self._dismiss_loading()
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _show_export_success(self, path: str, mime_type: str, client_email: str) -> None:
        self._dismiss_loading()
        actions = [("VIEW", lambda: self._view_file(path, mime_type)),
                   ("SAVE A COPY", lambda: self._save_as(path, mime_type)),
                   ("DELETE APP COPY", lambda: self._confirm_delete_report(path))]
        if platform == "android":
            actions += [("SHARE", lambda: self._share_file(path, mime_type))]
            if client_email:
                actions += [("EMAIL CLIENT", lambda: self._email_to_client(path, mime_type, client_email))]
        self._action_dialog("Report", export_success_text(path, platform == "android"), actions)

    def _action_dialog(self, title, text, actions):
        if self._dialog:
            self._dialog.dismiss()
        content = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        label = MDLabel(text=text, size_hint_y=None, theme_text_color="Custom", text_color=TEXT_DARK)
        label.bind(width=lambda inst, width: setattr(inst, "text_size", (width, None)))
        label.bind(texture_size=lambda inst, size: setattr(inst, "height", size[1] + dp(12)))
        content.add_widget(label)
        for name, action in actions:
            content.add_widget(tonal_button(name, on_release=action))
        content.bind(minimum_height=content.setter("height"))
        scroll = ScrollView(size_hint_y=None, height=dp(330))
        scroll.add_widget(content)
        self._dialog = MDDialog(title=title, type="custom", content_cls=scroll,
                                buttons=[MDFlatButton(text="CLOSE", on_release=lambda *_: self._dialog.dismiss())])
        self._dialog.open()

    def _show_history(self, offset=0):
        files = list_exported_reports(export_dir(MDApp.get_running_app()))
        if not files:
            self._show_message("Report History", "No exported reports yet. Export a proposal to create one.")
            return
        actions = []
        for path in files[offset:offset + 20]:
            kind = {".pdf": "pdf", ".xlsx": "excel", ".csv": "csv", ".pptx": "pptx"}[path.suffix.lower()]
            label = path.name if len(path.name) <= 30 else path.name[:27] + "..."
            actions.append((label, lambda selected=str(path), mime=MIME_TYPES[kind]: self._show_export_success(selected, mime, "")))
        if offset + 20 < len(files):
            actions.append(("OLDER REPORTS", lambda: self._show_history(offset + 20)))
        if offset:
            actions.append(("NEWER REPORTS", lambda: self._show_history(max(0, offset - 20))))
        self._action_dialog("Report History", "Most recent reports. Select one to view, save a copy, share, or delete its app copy.", actions)

    def _confirm_delete_report(self, path):
        if Path(path).resolve().parent != Path(export_dir(MDApp.get_running_app())).resolve():
            self._show_message("Cannot Delete", "Only reports in the app's report folder can be deleted here.")
            return
        def delete():
            try:
                Path(path).unlink()
                self._show_history()
            except OSError:
                self._show_message("Delete Failed", "Could not delete the report. Try again.")
        self._action_dialog("Delete App Copy?", "This removes the report stored by SolarQuote. Copies saved or shared elsewhere are kept.",
                            [("DELETE", delete), ("CANCEL", self._show_history)])

    def _save_as(self, path, mime_type, on_complete=None):
        """User-initiated copy. Optional callback receives destination or None."""
        if self._save_request is not None:
            self._show_message("Save in Progress", "Finish the current save dialog first.")
            return
        def completed(destination=None, error=None):
            self._save_request = None
            if on_complete:
                on_complete(destination)
            if error:
                self._show_message("Save Failed", "Could not save the copy. Check the destination and available space.")
            elif destination:
                self._show_message("Copy Saved", "Your copy is saved outside the app. Manage or delete it from your chosen location.")
        if platform != "android":
            try:
                from plyer import filechooser
                self._save_request = path
                def selection(selected):
                    if not selected:
                        Clock.schedule_once(lambda _dt: completed(), 0)
                        return
                    destination = selected[0]
                    def copy_file():
                        error = None
                        try:
                            if Path(destination).resolve() != Path(path).resolve():
                                shutil.copy2(path, destination)
                        except OSError as exc:
                            error = exc
                        Clock.schedule_once(lambda _dt: completed(destination if error is None else None, error), 0)
                    threading.Thread(target=copy_file, daemon=True).start()
                filechooser.save_file(title="Save report copy", path=Path(path).name, on_selection=selection)
            except Exception:
                log.exception("Save chooser unavailable")
                completed(error=True)
            return
        try:
            from android import activity as activity_events
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            Activity = autoclass("android.app.Activity")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            request_code = 8473
            def result(code, status, intent):
                if code != request_code:
                    return
                activity_events.unbind(on_activity_result=result)
                if status != Activity.RESULT_OK or intent is None:
                    Clock.schedule_once(lambda _dt: completed(), 0)
                    return
                uri = intent.getData()
                def copy_uri():
                    stream = None
                    destination, error = None, None
                    try:
                        stream = activity.getContentResolver().openOutputStream(uri)
                        if stream is None:
                            raise OSError("Destination cannot be opened")
                        with open(path, "rb") as source:
                            for chunk in iter(lambda: source.read(65536), b""):
                                stream.write(bytearray(chunk))
                        stream.flush()
                        destination = str(uri.toString())
                    except Exception as exc:
                        log.exception("Could not copy report to selected document")
                        error = exc
                    finally:
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception as exc:
                                error = exc
                                destination = None
                    Clock.schedule_once(lambda _dt: completed(destination, error), 0)
                threading.Thread(target=copy_uri, daemon=True, name="solarquote-save-copy").start()
            self._save_request = path
            activity_events.bind(on_activity_result=result)
            intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType(mime_type)
            intent.putExtra(Intent.EXTRA_TITLE, Path(path).name)
            def launch_failed():
                activity_events.unbind(on_activity_result=result)
                completed(error=True)
            launch_android_intent(activity, cast("android.content.Intent", intent), request_code, launch_failed)
        except Exception:
            log.exception("Could not open document save chooser")
            try:
                activity_events.unbind(on_activity_result=result)
            except (UnboundLocalError, AttributeError):
                pass
            completed(error=True)

    def choose_import_file(self, on_complete, mime_type="application/json"):
        """Read a user-selected Android document into a private temporary file.

        Callback receives the private path or None. The importer must delete a
        returned Android temporary file after importing. Desktop paths are the
        user's original file and must be kept.
        """
        if platform != "android":
            from plyer import filechooser
            filechooser.open_file(on_selection=lambda files: Clock.schedule_once(lambda _dt: on_complete(files[0] if files else None), 0))
            return
        if self._save_request is not None:
            self._show_message("Document Picker Busy", "Finish the current save or import dialog first.")
            on_complete(None)
            return
        def completed(path=None, error=None):
            self._save_request = None
            if error:
                self._show_message("Import Failed", "Could not read the backup. Check its format, permissions, and 20 MB size limit.")
            on_complete(path)
        try:
            from android import activity as activity_events
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            Activity = autoclass("android.app.Activity")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            request_code = 8474
            def result(code, status, intent):
                if code != request_code:
                    return
                activity_events.unbind(on_activity_result=result)
                if status != Activity.RESULT_OK or intent is None:
                    Clock.schedule_once(lambda _dt: completed(), 0)
                    return
                uri = intent.getData()
                app = MDApp.get_running_app()
                def read_document():
                    stream, private_path, error = None, None, None
                    try:
                        folder = Path(app.user_data_dir) / "imports"
                        folder.mkdir(parents=True, exist_ok=True)
                        descriptor, private_path = tempfile.mkstemp(prefix="backup-", suffix=".json", dir=str(folder))
                        os.close(descriptor)
                        stream = activity.getContentResolver().openInputStream(uri)
                        if stream is None:
                            raise OSError("Backup cannot be opened")
                        copy_document_stream(stream, private_path)
                    except Exception as exc:
                        log.exception("Could not read selected backup document")
                        error = exc
                        if private_path:
                            Path(private_path).unlink(missing_ok=True)
                        private_path = None
                    finally:
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception as exc:
                                error = exc
                                if private_path:
                                    Path(private_path).unlink(missing_ok=True)
                                private_path = None
                    Clock.schedule_once(lambda _dt: completed(private_path, error), 0)
                threading.Thread(target=read_document, daemon=True, name="solarquote-import-copy").start()
            self._save_request = "import"
            activity_events.bind(on_activity_result=result)
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType(mime_type)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            def launch_failed():
                activity_events.unbind(on_activity_result=result)
                completed(error=True)
            launch_android_intent(activity, cast("android.content.Intent", intent), request_code, launch_failed)
        except Exception:
            log.exception("Could not open backup document picker")
            try:
                activity_events.unbind(on_activity_result=result)
            except (UnboundLocalError, AttributeError):
                pass
            completed(error=True)

    def _content_uri_for(self, path: str):
        """Wraps a plain file path as a content:// Uri via the app's FileProvider
        -- required for handing a file to another app's Intent on Android 7+,
        which blocks sharing raw file:// paths between apps. See p4a_hooks.py
        and android_res/file_paths.xml for the provider/path-whitelist setup
        this depends on."""
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        FileProviderClass = autoclass("androidx.core.content.FileProvider")
        File = autoclass("java.io.File")
        activity = PythonActivity.mActivity
        return activity, FileProviderClass.getUriForFile(activity, FILEPROVIDER_AUTHORITY, File(path))

    def _view_file(self, path: str, mime_type: str) -> None:
        """Opens the exported file with whatever app is already installed and
        registered to handle it (a PDF reader, Office/WPS/Google Slides for
        .pptx) -- the same ACTION_VIEW behavior as tapping the file in a file
        manager, so the report is shown without this app needing to build and
        ship its own PDF/PPTX renderer."""
        try:
            if platform != "android":
                if os.name == "nt":
                    os.startfile(path)
                else:
                    import webbrowser
                    webbrowser.open(Path(path).resolve().as_uri())
                return
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            activity, uri = self._content_uri_for(path)

            intent = Intent(Intent.ACTION_VIEW)
            intent.setDataAndType(cast("android.net.Uri", uri), mime_type)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            launch_android_intent(activity, intent, on_error=lambda: self._show_message(
                "Can't Open File", "Could not open this file. Check that an app for this file type is installed."))
        except Exception as exc:
            log.warning("Could not open exported file: %s", exc)
            self._show_message(
                "Can't Open File",
                "Could not open this file. Check that an app for this file type is installed.",
            )

    def _share_file(self, path: str, mime_type: str) -> None:
        """Opens Android's native share sheet (WhatsApp, Viber, Telegram,
        Messenger, Drive, Bluetooth, email -- whatever's installed and
        registered to receive this file type)."""
        try:
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            String = autoclass("java.lang.String")
            activity, uri = self._content_uri_for(path)

            intent = Intent(Intent.ACTION_SEND)
            intent.setType(mime_type)
            intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            # createChooser's title param is typed CharSequence; pyjnius's static
            # overload resolution won't match a plain Python str against it (it
            # only auto-coerces to a concrete String-typed param), so wrap it as
            # a real java.lang.String -- CharSequence-compatible instance -- first.
            launch_android_intent(activity, Intent.createChooser(intent, String("Share Report")),
                                  on_error=lambda: self._show_message("Share Failed", "Could not open the share sheet."))
        except Exception as exc:
            log.warning("Could not share exported file: %s", exc)
            self._show_message("Share Failed", "Could not open the share sheet.")

    def _email_to_client(self, path: str, mime_type: str, client_email: str) -> None:
        """Opens the phone's email app with the client's address (from the
        Client Info screen) and the report already attached -- the installer
        reviews and taps Send themselves; nothing is sent automatically and no
        email credentials are stored by this app."""
        if not client_email:
            self._show_message(
                "No Client Email",
                "Add the client's email on the Client Info screen first, then export again.",
            )
            return
        try:
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            String = autoclass("java.lang.String")
            activity, uri = self._content_uri_for(path)

            intent = Intent(Intent.ACTION_SEND)
            intent.setType("message/rfc822")
            intent.putExtra(Intent.EXTRA_EMAIL, [client_email])
            intent.putExtra(Intent.EXTRA_SUBJECT, "Your Solar System Proposal")
            intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            # See _share_file's comment: createChooser's title param is typed
            # CharSequence, which pyjnius won't resolve from a plain Python str.
            launch_android_intent(activity, Intent.createChooser(intent, String("Send via Email")),
                                  on_error=lambda: self._show_message("Email Failed", "Could not open an email app."))
        except Exception as exc:
            log.warning("Could not open email app for export: %s", exc)
            self._show_message("Email Failed", "Could not open an email app.")

    def _save_project(self) -> None:
        app = MDApp.get_running_app()
        client_screen = app.root.get_screen("client")
        if client_screen.save_full_quote():
            self._show_message(
                "Saved",
                "The full quote -- Client Information through Savings & ROI -- has been saved.",
            )

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "roi"

    def _go_home(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "client"

    def _go_about(self) -> None:
        app = MDApp.get_running_app()
        app.state.about_return_to = self.name
        app.root.current = "about"
