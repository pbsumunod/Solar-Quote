"""Report screen (ported from the desktop app's ui/report.py).

Branding + preview + export group + disclaimer, same structure as desktop.
Company logo upload is dropped (no native file picker on Android without extra
work) -- company name only for now. Exports save into the app's external files
directory (Android/data/<package>/files/ on-device -- reachable via a file
manager or USB-to-PC, no runtime permission needed). After a successful export,
the confirmation dialog offers Share (Android's native share sheet -- WhatsApp,
Viber, Telegram, Drive, Bluetooth, whatever's installed) and Email to Client
(opens the phone's email app with the client's address from the Client Info
screen pre-filled and the file attached, letting the installer review before
sending -- no credentials stored, no automatic sending). Both go through a
FileProvider (android_res/file_paths.xml + the <provider> injected by
p4a_hooks.py at build time), since Android blocks apps from handing each other
raw file:// paths. See logic/reports.py for the actual PDF/Excel/CSV/PPTX
generation.
"""

import os
import shutil

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.spinner import MDSpinner

from logic.chart_series import DOD_FLOOR_COLOR, roi_chart_series, series_for_result
from logic.reports import DISCLAIMER, SCENARIO_ORDER, generate_csv, generate_excel, generate_pdf, generate_pptx
from ui_style import (
    ACCENT, BUILD_LABEL, TEXT_DARK, about_button, bottom_back_action, header_actions, icon_button, keep_focused_field_visible, m3_field, save_button,
    screen_header, section_card, section_label, tonal_button, with_bg,
)
from widgets.line_chart import LineChart

MIME_TYPES = {
    "pdf": "application/pdf",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# Must exactly match p4a_hooks.py's FILEPROVIDER_AUTHORITY (package.domain +
# "." + package.name + ".fileprovider" from buildozer.spec).
FILEPROVIDER_AUTHORITY = "org.solarclientfinder.solarclientfinder.fileprovider"


def export_dir(app) -> str:
    """Return the Android Downloads directory, with a safe app-data fallback."""
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Environment = autoclass("android.os.Environment")
            context = PythonActivity.mActivity
            ext_dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if ext_dir is not None:
                path = ext_dir.getAbsolutePath()
                os.makedirs(path, exist_ok=True)
                if os.access(path, os.W_OK):
                    return path
            # Scoped-storage fallback still places files in a Downloads-named
            # folder when Android does not grant direct public-folder access.
            ext_dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            if ext_dir is not None:
                return ext_dir.getAbsolutePath()
        except Exception:
            pass
    return app.user_data_dir


class ReportScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "report"
        self._dialog: MDDialog | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
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
        export_row1 = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        export_row1.add_widget(tonal_button(
            "EXPORT PDF", on_release=lambda: self._export("pdf"),
        ))
        export_row1.add_widget(tonal_button(
            "EXPORT EXCEL", on_release=lambda: self._export("excel"),
        ))
        export_card.add_widget(export_row1)

        export_row2 = MDBoxLayout(spacing=dp(8), size_hint_y=None, height=dp(48))
        export_row2.add_widget(tonal_button(
            "EXPORT CSV", on_release=lambda: self._export("csv"),
        ))
        export_row2.add_widget(tonal_button(
            "EXPORT POWERPOINT", on_release=lambda: self._export("pptx"),
        ))
        export_card.add_widget(export_row2)
        form.add_widget(export_card)

        form.add_widget(section_label("information-outline", "Disclaimer"))
        form.add_widget(MDLabel(
            text=DISCLAIMER, theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None, height=dp(90),
        ))
        form.add_widget(MDLabel(
            text=f"Build {BUILD_LABEL}", font_style="Caption", halign="center",
            theme_text_color="Custom", text_color=TEXT_DARK, size_hint_y=None, height=dp(20),
        ))
        form.add_widget(bottom_back_action(self._go_back))

        scroll.add_widget(form)
        keep_focused_field_visible(scroll, form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _collect_data(self) -> dict:
        app = MDApp.get_running_app()
        sm = app.root
        return {
            "company_name": self.company_name_field.text.strip(),
            "client": sm.get_screen("client").get_report_data(),
            "consumption": sm.get_screen("consumption").get_report_data(),
            "solar": sm.get_screen("solar").get_report_data(),
            "battery": sm.get_screen("battery").get_report_data(),
            "system_design": sm.get_screen("system_design").get_report_data(),
            "simulation": sm.get_screen("simulation").get_report_data(),
            "roi": sm.get_screen("roi").get_report_data(),
        }

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
        app = MDApp.get_running_app()
        tmp_dir = os.path.join(app.user_data_dir, "chart_tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir

    def _save_chart_png(self, chart: LineChart, image_path: str, label: str) -> str:
        """Renders an off-tree LineChart to a PNG via Kivy's export_as_image, which
        renders into its own offscreen Fbo -- the widget doesn't need to be added
        to the Window to work.

        export_to_png()/Image.save() can fail *silently* (returns False, raises
        nothing) if the GPU texture readback comes back with no pixel data --
        observed on-device even though it's reliable on desktop GPU drivers. We
        call the lower-level save() directly so we can check its return value and
        retry with fresh idle-pumped frames rather than quietly handing the export
        a path with nothing behind it (which then fails much later, confusingly,
        inside python-pptx's/fpdf2's own file open)."""
        from kivy.base import EventLoop
        EventLoop.ensure_window()

        saved = False
        for _attempt in range(5):
            # The axis tick Labels' textures are generated on a Clock trigger,
            # and the GPU needs a moment to finish rendering the Fbo -- pump a
            # few idle frames before each attempt, not just the first.
            for _ in range(3):
                EventLoop.idle()
            saved = chart.export_as_image().save(image_path, flipped=False)
            if saved and os.path.exists(image_path):
                break
        if not saved:
            raise RuntimeError(
                f"Could not render the {label} chart image "
                "(the device's graphics driver returned no image data after 5 attempts)."
            )
        if not os.path.exists(image_path):
            raise RuntimeError(
                f"The {label} chart image vanished right after being saved "
                f"(expected at {image_path})."
            )

        # export_as_image() renders onto a transparent Fbo (Kivy clears it with
        # alpha 0) -- fine for the live in-app chart, which sits on a themed/
        # tinted screen background on purpose, but unreadable once the PNG lands
        # on a colored PDF/PPTX page: the chart's dark axis-label text can end up
        # nearly invisible against a dark slide background. Flatten onto opaque
        # white here, at export time only, so the exported image always has good
        # contrast regardless of what it's placed on.
        from PIL import Image as PILImage
        with PILImage.open(image_path) as im:
            flattened = PILImage.new("RGB", im.size, "white")
            flattened.paste(im, mask=im.convert("RGBA").split()[3])
            flattened.save(image_path)

        return image_path

    def _render_scenario_charts(self, data: dict) -> dict:
        """Renders each weather scenario's Simulation-tab chart to a standalone PNG
        (same series/colors as the live chart, via logic/chart_series.py), for the
        PowerPoint export."""
        battery_total_kwh = data["battery"]["total_kwh"]
        battery_dod_pct = data["battery"]["dod_pct"]
        dod_floor_kwh = battery_total_kwh * (1 - battery_dod_pct / 100)
        hline = {"y": dod_floor_kwh, "label": "DOD Floor", "color": DOD_FLOOR_COLOR}
        scenario_results = data["simulation"]["scenario_results"]
        tmp_dir = self._chart_tmp_dir()

        images = {}
        for name in SCENARIO_ORDER:
            result = scenario_results.get(name)
            if result is None:
                continue
            series, x_labels, _hours = series_for_result(result, battery_total_kwh)
            chart = LineChart(size_hint=(None, None), size=(1600, 700))
            chart.set_data(series, x_labels, hline=hline)
            image_path = os.path.join(tmp_dir, f"chart_{name.lower()}.png")
            images[name] = self._save_chart_png(chart, image_path, f"{name} scenario")
        return images

    def _render_roi_chart(self, data: dict) -> str:
        """Renders the ROI screen's cumulative-cash-flow chart (same series/colors
        as the live chart, via logic/chart_series.py) to a standalone PNG, for the
        PDF and PowerPoint exports."""
        roi = data["roi"]
        series, x_labels, vline = roi_chart_series(roi["system_cost"], roi["projection_rows"], roi["payback_years"])
        chart = LineChart(size_hint=(None, None), size=(1600, 700))
        chart.set_data(series, x_labels, vline=vline, fill_index=0)
        image_path = os.path.join(self._chart_tmp_dir(), "chart_roi.png")
        return self._save_chart_png(chart, image_path, "ROI")

    def _cleanup_chart_images(self, image_paths: list) -> None:
        for path in image_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        tmp_dir = os.path.dirname(image_paths[0]) if image_paths else ""
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _export(self, kind: str) -> None:
        # _save_chart_png() pumps EventLoop.idle() while it waits on the GPU,
        # which also dispatches any queued touch events -- a double-tap on an
        # export button can otherwise re-enter this method mid-render, and
        # whichever call finishes first deletes chart_tmp/ (see
        # _cleanup_chart_images) out from under the other one still rendering.
        if getattr(self, "_exporting", False):
            return
        self._exporting = True
        self._show_loading(f"Generating {kind.upper()} report...")
        # Report generation (PDF/PPTX chart rendering especially) blocks the
        # main thread for a few seconds -- scheduling it a frame later lets
        # Kivy actually paint the loading dialog first instead of freezing
        # with nothing on screen until the work is done.
        Clock.schedule_once(lambda _dt: self._do_export(kind), 0)

    def _show_loading(self, text: str) -> None:
        if self._dialog:
            self._dialog.dismiss()
        content = MDBoxLayout(
            orientation="horizontal", spacing=dp(16), padding=dp(8),
            size_hint_y=None, height=dp(48),
        )
        content.add_widget(MDSpinner(
            size_hint=(None, None), size=(dp(32), dp(32)), active=True, color=ACCENT,
        ))
        content.add_widget(MDLabel(
            text=text, halign="center", valign="middle", text_size=(dp(220), None),
            theme_text_color="Custom", text_color=TEXT_DARK,
        ))
        self._dialog = MDDialog(title="", type="custom", content_cls=content, auto_dismiss=False)
        self._dialog.open()

    def _do_export(self, kind: str) -> None:
        try:
            app = MDApp.get_running_app()
            data = self._collect_data()
            out_dir = export_dir(app)
            filenames = {"pdf": "solar_proposal.pdf", "excel": "solar_proposal.xlsx",
                         "csv": "solar_proposal.csv", "pptx": "solar_proposal.pptx"}
            path = os.path.join(out_dir, filenames[kind])
            chart_image_paths = []
            try:
                if kind == "pdf":
                    roi_chart_image = self._render_roi_chart(data)
                    scenario_images = self._render_scenario_charts(data)
                    chart_image_paths = [roi_chart_image] + list(scenario_images.values())
                    generate_pdf(path, data, roi_chart_image=roi_chart_image, scenario_images=scenario_images)
                elif kind == "excel":
                    generate_excel(path, data)
                elif kind == "csv":
                    generate_csv(path, data)
                elif kind == "pptx":
                    roi_chart_image = self._render_roi_chart(data)
                    chart_images = self._render_scenario_charts(data)
                    chart_image_paths = [roi_chart_image] + list(chart_images.values())
                    generate_pptx(path, data, chart_images=chart_images, roi_chart_image=roi_chart_image)
            except Exception as exc:
                self._show_message("Export Failed", f"Could not generate the {kind.upper()} report:\n{exc}")
                return
            finally:
                if chart_image_paths:
                    self._cleanup_chart_images(chart_image_paths)
            self._show_export_success(path, MIME_TYPES[kind], data["client"].get("email", ""))
        finally:
            self._exporting = False

    def _show_message(self, title: str, text: str) -> None:
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _show_export_success(self, path: str, mime_type: str, client_email: str) -> None:
        buttons = []
        if platform == "android":
            buttons.append(MDFlatButton(
                text="VIEW", text_color=ACCENT,
                on_release=lambda *_: self._view_file(path, mime_type),
            ))
            buttons.append(MDFlatButton(
                text="EMAIL TO CLIENT", text_color=ACCENT,
                on_release=lambda *_: self._email_to_client(path, mime_type, client_email),
            ))
            buttons.append(MDFlatButton(
                text="SHARE", text_color=ACCENT,
                on_release=lambda *_: self._share_file(path, mime_type),
            ))
        buttons.append(MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss()))

        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(title="Exported", text=f"Saved to:\n{path}", buttons=buttons)
        self._dialog.open()

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
            from jnius import autoclass, cast
            Intent = autoclass("android.content.Intent")
            activity, uri = self._content_uri_for(path)

            intent = Intent(Intent.ACTION_VIEW)
            intent.setDataAndType(cast("android.net.Uri", uri), mime_type)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            activity.startActivity(intent)
        except Exception as exc:
            self._show_message(
                "Can't Open File",
                f"No app on this device is set up to open this file type:\n{exc}",
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
            activity.startActivity(Intent.createChooser(intent, String("Share Report")))
        except Exception as exc:
            self._show_message("Share Failed", f"Could not open the share sheet:\n{exc}")

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
            activity.startActivity(Intent.createChooser(intent, String("Send via Email")))
        except Exception as exc:
            self._show_message("Email Failed", f"Could not open an email app:\n{exc}")

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
