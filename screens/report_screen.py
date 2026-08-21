"""Report screen (ported from the desktop app's ui/report.py).

Branding + preview + export group + disclaimer, same structure as desktop.
Company logo upload is dropped (no native file picker on Android without extra
work) -- company name only for now. Exports save into the app's external files
directory (Android/data/<package>/files/ on-device -- reachable via a file
manager or USB-to-PC, no runtime permission needed) rather than using a native
"Save As" dialog or a Share sheet, since python-for-android's default template
has no FileProvider configured for sharing files to other apps (that would need
untested custom AndroidManifest/XML work). The exact save path is shown after
each export. See logic/reports.py for the actual PDF/Excel/CSV/PPTX generation.
"""

import os
import shutil

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from logic.chart_series import DOD_FLOOR_COLOR, roi_chart_series, series_for_result
from logic.reports import DISCLAIMER, SCENARIO_ORDER, generate_csv, generate_excel, generate_pdf, generate_pptx
from ui_style import ACCENT, TEXT_DARK, m3_field, screen_header, section_card, section_label, tonal_button, with_bg
from widgets.line_chart import LineChart


def export_dir(app) -> str:
    """The app's external files directory on Android (no runtime permission
    needed, reachable via a file manager/USB); falls back to user_data_dir
    for desktop testing, where pyjnius/Android APIs aren't available."""
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            context = PythonActivity.mActivity
            ext_dir = context.getExternalFilesDir(None)
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
        root.add_widget(screen_header("Report", step=8, on_back=self._go_back))

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

        scroll.add_widget(form)
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
                chart_image_paths = [roi_chart_image]
                generate_pdf(path, data, roi_chart_image=roi_chart_image)
            elif kind == "excel":
                generate_excel(path, data)
            elif kind == "csv":
                generate_csv(path, data)
            elif kind == "pptx":
                chart_images = self._render_scenario_charts(data)
                roi_chart_image = self._render_roi_chart(data)
                chart_image_paths = list(chart_images.values()) + [roi_chart_image]
                generate_pptx(path, data, chart_images=chart_images, roi_chart_image=roi_chart_image)
        except Exception as exc:
            self._show_message("Export Failed", f"Could not generate the {kind.upper()} report:\n{exc}")
            return
        finally:
            if chart_image_paths:
                self._cleanup_chart_images(chart_image_paths)
        self._show_message("Exported", f"Saved to:\n{path}")

    def _show_message(self, title: str, text: str) -> None:
        if self._dialog:
            self._dialog.dismiss()
        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[MDFlatButton(text="OK", text_color=ACCENT, on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _go_back(self) -> None:
        app = MDApp.get_running_app()
        app.root.current = "roi"
