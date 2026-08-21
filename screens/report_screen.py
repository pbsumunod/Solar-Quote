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
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from logic.chart_series import series_for_result
from logic.reports import DISCLAIMER, SCENARIO_ORDER, generate_csv, generate_excel, generate_pdf, generate_pptx
from ui_style import ACCENT, TEXT_DARK, WHITE, green_field, top_app_bar, with_bg
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
        root.add_widget(top_app_bar("Report", on_back=self._go_back))

        scroll = ScrollView()
        form = MDBoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        form.add_widget(self._section_label("Report Branding"))
        self.company_name_field = green_field(hint_text="Company Name (optional)")
        form.add_widget(self.company_name_field)

        form.add_widget(self._section_label("Report Preview"))
        refresh_btn = MDRaisedButton(
            text="Refresh Preview", size_hint_x=1, md_bg_color=ACCENT, text_color=WHITE,
            on_release=lambda *_: self._refresh_preview(),
        )
        form.add_widget(refresh_btn)
        self.preview_label = with_bg(MDLabel(
            text="Tap Refresh Preview to see a summary.", theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None,
        ))
        self.preview_label.bind(texture_size=lambda _i, val: setattr(self.preview_label, "height",
                                                                       max(dp(80), val[1] + dp(16))))
        self.preview_label.bind(width=lambda _i, val: setattr(self.preview_label, "text_size", (val - dp(16), None)))
        form.add_widget(self.preview_label)

        form.add_widget(self._section_label("Export"))
        export_row1 = MDBoxLayout(spacing=dp(6), size_hint_y=None, height=dp(48))
        pdf_btn = MDRaisedButton(text="EXPORT PDF", md_bg_color=ACCENT, text_color=WHITE,
                                  on_release=lambda *_: self._export("pdf"))
        excel_btn = MDRaisedButton(text="EXPORT EXCEL", md_bg_color=ACCENT, text_color=WHITE,
                                    on_release=lambda *_: self._export("excel"))
        export_row1.add_widget(pdf_btn)
        export_row1.add_widget(excel_btn)
        form.add_widget(export_row1)

        export_row2 = MDBoxLayout(spacing=dp(6), size_hint_y=None, height=dp(48))
        csv_btn = MDRaisedButton(text="EXPORT CSV", md_bg_color=ACCENT, text_color=WHITE,
                                  on_release=lambda *_: self._export("csv"))
        pptx_btn = MDRaisedButton(text="EXPORT POWERPOINT", md_bg_color=ACCENT, text_color=WHITE,
                                   on_release=lambda *_: self._export("pptx"))
        export_row2.add_widget(csv_btn)
        export_row2.add_widget(pptx_btn)
        form.add_widget(export_row2)

        form.add_widget(self._section_label("Disclaimer"))
        form.add_widget(MDLabel(
            text=DISCLAIMER, theme_text_color="Custom", text_color=TEXT_DARK,
            size_hint_y=None, height=dp(90),
        ))

        scroll.add_widget(form)
        root.add_widget(scroll)
        self.add_widget(root)

    def _section_label(self, text: str) -> MDLabel:
        return MDLabel(
            text=text, bold=True, size_hint_y=None, height=dp(24),
            theme_text_color="Custom", text_color=TEXT_DARK,
        )

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

    def _render_scenario_charts(self, data: dict) -> dict:
        """Renders each weather scenario's Simulation-tab chart to a standalone PNG
        (same series/colors as the live chart, via logic/chart_series.py) for the
        PowerPoint export. Uses Kivy's export_to_png on an off-tree LineChart, which
        renders into its own offscreen Fbo -- it doesn't need to be added to the
        Window to work. Images are written under a scratch subfolder of user_data_dir
        and removed again in _cleanup_chart_images once the pptx has embedded them."""
        app = MDApp.get_running_app()
        battery_total_kwh = data["battery"]["total_kwh"]
        scenario_results = data["simulation"]["scenario_results"]
        tmp_dir = os.path.join(app.user_data_dir, "chart_tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        images = {}
        for name in SCENARIO_ORDER:
            result = scenario_results.get(name)
            if result is None:
                continue
            series, x_labels, _hours = series_for_result(result, battery_total_kwh)
            chart = LineChart(size_hint=(None, None), size=(1600, 700))
            chart.set_data(series, x_labels)
            # The axis tick Labels' textures are generated on a Clock trigger, not
            # synchronously in set_data() -- without pumping a few idle frames first,
            # export_to_png captures the chart lines but with blank axis labels.
            from kivy.base import EventLoop
            EventLoop.ensure_window()
            for _ in range(5):
                EventLoop.idle()
            image_path = os.path.join(tmp_dir, f"chart_{name.lower()}.png")
            chart.export_to_png(image_path)
            images[name] = image_path
        return images

    def _cleanup_chart_images(self, chart_images: dict) -> None:
        for path in chart_images.values():
            try:
                os.remove(path)
            except OSError:
                pass
        tmp_dir = os.path.dirname(next(iter(chart_images.values()), "")) or ""
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _export(self, kind: str) -> None:
        app = MDApp.get_running_app()
        data = self._collect_data()
        out_dir = export_dir(app)
        filenames = {"pdf": "solar_proposal.pdf", "excel": "solar_proposal.xlsx",
                     "csv": "solar_proposal.csv", "pptx": "solar_proposal.pptx"}
        path = os.path.join(out_dir, filenames[kind])
        chart_images = {}
        try:
            if kind == "pdf":
                generate_pdf(path, data)
            elif kind == "excel":
                generate_excel(path, data)
            elif kind == "csv":
                generate_csv(path, data)
            elif kind == "pptx":
                chart_images = self._render_scenario_charts(data)
                generate_pptx(path, data, chart_images=chart_images)
        except Exception as exc:
            self._show_message("Export Failed", f"Could not generate the {kind.upper()} report:\n{exc}")
            return
        finally:
            if chart_images:
                self._cleanup_chart_images(chart_images)
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
