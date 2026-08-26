"""PDF (fpdf2), Excel (openpyxl), CSV, and PowerPoint (python-pptx) report export.

Redesigned from the desktop app's reports.py for two reasons: reportlab's optional
C accelerator and python-pptx's lxml dependency both needed replacing/patching to
build for Android (see mobile_app/recipes/lxml and the Phase-2 build notes), and the
desktop version embeds matplotlib chart images, which this app doesn't have (charts
here are hand-drawn Kivy widgets, not matplotlib Figures) -- so exports are text/table
based, no embedded charts. generate_excel and generate_csv are otherwise a close port
of the desktop version (openpyxl's API is identical); generate_pdf and generate_pptx
are new, built directly against fpdf2/python-pptx instead of reportlab.

Currency uses a "PHP" prefix rather than the peso sign (U+20B1) -- fpdf2's built-in
core fonts don't have that glyph without bundling a custom TTF, and the rest of the
app already made this same choice for the same reason (Android font-glyph coverage).

fpdf/openpyxl/pptx are imported lazily, inside each generate_* function, rather than
at module level: this file is imported by report_screen.py, which main.py imports at
startup, so a module-level import failure in any one of these (e.g. a library that
built successfully but fails to actually import at runtime on a given device) would
crash the whole app before it even opens, not just the Report tab's export buttons.
"""

import sys
from types import ModuleType

from logic.calculations import HOUR_LABELS

DISCLAIMER = (
    "Solar system sizing is an engineering estimate based on the information and assumptions "
    "provided. Actual solar production, electricity consumption, weather conditions, equipment "
    "specifications, installation conditions, and utility requirements may affect actual "
    "performance. Final system design should be verified by a qualified solar/electrical "
    "professional."
)

SCENARIO_ORDER = ["Sunny", "Cloudy", "Rainy"]

# Matches ui_style.py's Client Info tab palette (ACCENT/ON_SURFACE/ON_SURFACE_VARIANT/
# SURFACE_CONTAINER) so the PDF reads as the same brand as the app itself, rather than
# the unrelated blue this report used before.
PRIMARY_RGB = (46, 126, 52)     # ui_style.ACCENT (#2E7E34)
TEXT_RGB = (28, 28, 24)         # ui_style.ON_SURFACE
MUTED_RGB = (72, 71, 62)        # ui_style.ON_SURFACE_VARIANT
BAND_RGB = (243, 241, 234)      # ui_style.SURFACE_CONTAINER

PPTX_THEME = {
    "cover": ("0F2A4A", "F4A300"),
    "client": ("EEF2F6", "DCE7F2"),
    "system": ("F4A300", "FFE8B3"),
    "savings": ("173A2E", "2F9E44"),
    "closing": ("1E4E7F", "2B6CB0"),
}

# Matches widgets/weather_bg.py's GRADIENTS so the chart-scenario slides feel like the
# same weather theming the user already sees on the Simulation tab.
PPTX_WEATHER_THEME = {
    "Sunny": ("FFF2BF", "FA9E66"),
    "Cloudy": ("EBEDF2", "B8BAC2"),
    "Rainy": ("294D80", "84B3D9"),
}

ROI_SLIDE_PHOTO = "assets/images/roi_slide.jpg"


# --- Excel export --------------------------------------------------------------

def generate_excel(path: str, data: dict) -> None:
    from openpyxl import Workbook

    client = data["client"]
    consumption = data["consumption"]
    solar = data["solar"]
    battery = data["battery"]
    system_design = data["system_design"]
    simulation = data["simulation"]
    roi = data["roi"]

    wb = Workbook()

    ws = wb.active
    ws.title = "Client & Assumptions"
    for row in [
        ["Client Name", client["client_name"]], ["Project Location", client["project_location"]],
        ["Contact Number", client["contact_number"]], ["Email", client["email"]],
        ["Date", client["project_date"]], ["Country", client.get("country", "")], [],
        ["Monthly Consumption (kWh)", client["monthly_kwh"]],
        ["Day/Night Ratio", f"{client['daytime_pct']}/{client['nighttime_pct']}"],
        ["Electricity Rate (PHP/kWh)", client["electricity_rate"]],
        ["Peak Sun Hours", solar["peak_sun_hours"]], ["Solar System Efficiency (%)", solar["efficiency_pct"]],
        ["Battery DOD (%)", battery["dod_pct"]], ["Battery Efficiency (%)", battery["efficiency_pct"]],
        ["Inverter Efficiency (%)", system_design["efficiency_pct"]],
        ["Sunny Factor (%)", simulation["weather_factors"].get("Sunny", "")],
        ["Cloudy Factor (%)", simulation["weather_factors"].get("Cloudy", "")],
        ["Rainy Factor (%)", simulation["weather_factors"].get("Rainy", "")],
        ["Electricity Inflation (%)", roi["inflation_pct"]],
        ["System Cost (PHP)", roi["system_cost"]],
    ]:
        ws.append(row)

    ws2 = wb.create_sheet("Hourly Consumption")
    ws2.append(["Hour", "Consumption (kWh)"])
    for label, kwh in zip(HOUR_LABELS, consumption["hourly_kwh"]):
        ws2.append([label, round(kwh, 3)])

    ws3 = wb.create_sheet("Hourly Solar Production")
    ws3.append(["Hour"] + SCENARIO_ORDER)
    per_scenario_hourly = {name: simulation["scenario_results"][name] for name in SCENARIO_ORDER
                            if name in simulation["scenario_results"]}
    for i, label in enumerate(HOUR_LABELS):
        ws3.append([label] + [round(per_scenario_hourly[name].hours[i].solar_kwh, 3)
                               for name in SCENARIO_ORDER if name in per_scenario_hourly])

    if "Sunny" in simulation["scenario_results"]:
        ws4 = wb.create_sheet("Hourly Simulation (Sunny)")
        ws4.append([
            "Hour", "Consumption", "Solar", "Solar to Load", "Battery Charge", "Battery Discharge",
            "Grid Purchase", "Grid Export", "Curtailed", "Battery SOC End (kWh)", "Battery SOC End (%)",
        ])
        for h in simulation["scenario_results"]["Sunny"].hours:
            ws4.append([
                h.hour_label, round(h.consumption_kwh, 3), round(h.solar_kwh, 3), round(h.solar_to_load_kwh, 3),
                round(h.battery_charge_kwh, 3), round(h.battery_discharge_kwh, 3), round(h.grid_purchase_kwh, 3),
                round(h.grid_export_kwh, 3), round(h.curtailed_kwh, 3), round(h.soc_end_kwh, 3),
                round(h.soc_end_pct, 1),
            ])

    ws5 = wb.create_sheet("Weather Scenarios")
    ws5.append(["Scenario", "Solar Production", "Grid Purchase", "Battery Usage", "Excess Energy"])
    for name in SCENARIO_ORDER:
        result = simulation["scenario_results"].get(name)
        if result is None:
            continue
        battery_usage = result.total_battery_charge_kwh + result.total_battery_discharge_kwh
        excess = result.total_grid_export_kwh + result.total_curtailed_kwh
        ws5.append([name, round(result.total_solar_kwh, 2), round(result.total_grid_purchase_kwh, 2),
                    round(battery_usage, 2), round(excess, 2)])

    ws6 = wb.create_sheet("Savings & ROI")
    for row in [
        ["Estimated Monthly Savings (PHP)", roi["monthly_savings"]],
        ["Estimated Annual Savings (PHP)", roi["annual_savings"]],
        ["System Cost (PHP)", roi["system_cost"]],
        ["Payback Period (years)", roi["payback_years"]],
        ["Total Savings (PHP)", roi["total_savings"]],
        ["Net Benefit (PHP)", roi["net_benefit"]],
        ["Return on Investment (%)", roi["roi_pct"]],
    ]:
        ws6.append(row)

    ws7 = wb.create_sheet("Financial Projection")
    ws7.append([
        "Year", "Electricity Rate", "Grid Cost Without Solar", "Grid Cost With Solar",
        "Electricity Savings", "Maintenance", "Net Savings", "Cumulative Cash Flow",
    ])
    for row in roi["projection_rows"]:
        ws7.append([
            row.year, round(row.electricity_rate, 2), round(row.grid_cost_without_solar, 2),
            round(row.grid_cost_with_solar, 2), round(row.electricity_savings, 2),
            round(row.maintenance, 2), round(row.net_savings, 2), round(row.cumulative_cash_flow, 2),
        ])

    wb.save(path)


# --- CSV export ------------------------------------------------------------

def generate_csv(path: str, data: dict) -> None:
    import csv

    client = data["client"]
    roi = data["roi"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Client Name", client["client_name"]])
        writer.writerow(["Monthly Consumption (kWh)", client["monthly_kwh"]])
        writer.writerow(["System Cost (PHP)", roi["system_cost"]])
        writer.writerow(["Estimated Annual Savings (PHP)", roi["annual_savings"]])
        writer.writerow(["Payback Period (years)", roi["payback_years"]])
        writer.writerow([])
        writer.writerow([
            "Year", "Electricity Rate", "Grid Cost Without Solar", "Grid Cost With Solar",
            "Electricity Savings", "Maintenance", "Net Savings", "Cumulative Cash Flow",
        ])
        for row in roi["projection_rows"]:
            writer.writerow([
                row.year, round(row.electricity_rate, 2), round(row.grid_cost_without_solar, 2),
                round(row.grid_cost_with_solar, 2), round(row.electricity_savings, 2),
                round(row.maintenance, 2), round(row.net_savings, 2), round(row.cumulative_cash_flow, 2),
            ])


# --- PDF export --------------------------------------------------------------

def _install_fonttools_compat() -> None:
    """Keep fpdf2's core-font exports independent of fontTools native modules.

    fpdf2 imports fontTools even though this report uses only its built-in Helvetica
    font. Some APK builds package host-architecture extensions (for example
    ``bezierTools`` and ``varLib.iup``), so any real fontTools import can fail before
    PDF generation begins. Supplying only fpdf2's import-time API bypasses all of
    those optional extensions. Custom TTF and SVG-font processing deliberately raises
    a clear error instead of loading an incompatible native library.
    """
    def unsupported(*_args, **_kwargs):
        raise RuntimeError(
            "Custom TrueType fonts are not supported in this Android build; "
            "use the report's built-in Helvetica font."
        )

    font_tools = ModuleType("fontTools")
    font_tools.__path__ = []
    tt_lib = ModuleType("fontTools.ttLib")
    tt_lib.TTFont = unsupported
    subset = ModuleType("fontTools.subset")
    svg_lib = ModuleType("fontTools.svgLib")
    svg_lib.__path__ = []
    svg_path = ModuleType("fontTools.svgLib.path")
    svg_path.parse_path = unsupported
    pens = ModuleType("fontTools.pens")
    pens.__path__ = []
    base_pen = ModuleType("fontTools.pens.basePen")

    class BasePen:
        pass

    base_pen.BasePen = BasePen
    font_tools.ttLib = tt_lib
    font_tools.subset = subset
    font_tools.svgLib = svg_lib
    font_tools.pens = pens
    svg_lib.path = svg_path
    pens.basePen = base_pen
    for module in (font_tools, tt_lib, subset, svg_lib, svg_path, pens, base_pen):
        sys.modules[module.__name__] = module

def _pdf_heading(pdf, text: str) -> None:
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*PRIMARY_RGB)
    pdf.cell(0, 10, text, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*PRIMARY_RGB)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)


def _pdf_kv_table(pdf, pairs: list[tuple[str, str]]) -> None:
    pdf.set_font("Helvetica", "", 10)
    for i, (k, v) in enumerate(pairs):
        if i % 2 == 1:
            pdf.set_fill_color(*BAND_RGB)
            fill = True
        else:
            fill = False
        pdf.set_text_color(*MUTED_RGB)
        pdf.cell(70, 7, str(k), align="L", fill=fill)
        pdf.set_text_color(*TEXT_RGB)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, str(v), align="L", new_x="LMARGIN", new_y="NEXT", fill=fill)
        pdf.set_font("Helvetica", "", 10)
    pdf.ln(4)


def _pdf_watermark(pdf, text: str) -> None:
    """Draw a diagonal watermark across the current page."""
    pdf.save_state()
    pdf.set_font("Helvetica", "B", 60)
    pdf.set_text_color(200, 200, 200)
    pdf.translate(pdf.w / 2, pdf.h / 2)
    pdf.rotate(45)
    pdf.cell(0, 0, text, align="C")
    pdf.restore_state()


def generate_pdf(
    path: str, data: dict, roi_chart_image: str | None = None, scenario_images: dict | None = None,
    watermark: str | None = None,
) -> None:
    """roi_chart_image: optional path to a pre-rendered PNG of the ROI screen's
    cumulative cash-flow chart (see report_screen.py's _render_roi_chart) --
    embedded right after the Savings & ROI table if provided.

    scenario_images: optional {scenario_name: png_path} (see report_screen.py's
    _render_scenario_charts) -- for each scenario present in both this dict and
    data["simulation"]["scenario_results"], adds a page with that scenario's
    hourly chart and a summary of its totals, in SCENARIO_ORDER."""
    _install_fonttools_compat()
    from fpdf import FPDF

    client = data["client"]
    consumption = data["consumption"]
    solar = data["solar"]
    battery = data["battery"]
    system_design = data["system_design"]
    simulation = data["simulation"]
    roi = data["roi"]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if watermark:
        _pdf_watermark(pdf, watermark)

    title = data.get("company_name") or "Solar Proposal"
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*PRIMARY_RGB)
    pdf.cell(0, 14, title, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*TEXT_RGB)
    pdf.cell(0, 8, f"Solar System Proposal for {client['client_name'] or 'Prospective Client'}",
             align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED_RGB)
    pdf.cell(0, 6, client["project_date"], align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    _pdf_heading(pdf, "Client Profile")
    _pdf_kv_table(pdf, [
        ("Client Name", client["client_name"] or "-"),
        ("Location", client["project_location"] or "-"),
        ("Contact", client["contact_number"] or "-"),
        ("Email", client["email"] or "-"),
        ("Country", client.get("country") or "-"),
        ("Monthly Consumption", f"{client['monthly_kwh']:.0f} kWh"),
        ("Day / Night Split", f"{client['daytime_pct']}% / {client['nighttime_pct']}%"),
        ("Daily Consumption", f"{consumption['daily_kwh']:.2f} kWh"),
        ("Peak Hourly Load", f"{consumption['peak_kwh']:.2f} kWh"),
    ])

    _pdf_heading(pdf, "Recommended System")
    _pdf_kv_table(pdf, [
        ("Solar Array", f"{solar['total_kw']:.2f} kWp"),
        ("Battery Storage", f"{battery['total_kwh']:.2f} kWh (usable {battery['usable_kwh']:.2f} kWh)"),
        ("Inverter", f"{system_design['rated_power_kw']:.2f} kW "
                      f"(efficiency {system_design['efficiency_pct']:.0f}%)"),
    ])

    _pdf_heading(pdf, "Engineering Notes")
    pdf.set_font("Helvetica", "", 10)
    for ok, text in system_design["warnings"]:
        pdf.set_text_color(*(46, 158, 68) if ok else (192, 57, 43))
        mark = "[OK]" if ok else "[!]"
        # Explicit width (not 0/"auto") -- width=0 hits an fpdf2 edge case here
        # after several page-break-adjacent calls ("not enough horizontal space").
        # new_x/new_y: multi_cell()'s own default is new_x=XPos.RIGHT, which for a
        # full-page-width cell leaves the cursor sitting at the *right* margin --
        # the next line then started printing from there and ran off the page
        # edge instead of stacking underneath. Force it back to the left margin.
        pdf.multi_cell(pdf.epw, 6, f"{mark} {text}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if scenario_images:
        for name in SCENARIO_ORDER:
            image_path = scenario_images.get(name)
            result = simulation["scenario_results"].get(name)
            if not image_path or result is None:
                continue
            pdf.add_page()
            if watermark:
                _pdf_watermark(pdf, watermark)
            _pdf_heading(pdf, f"{name} Day Simulation")
            pdf.image(image_path, w=pdf.epw)
            pdf.ln(4)
            battery_usage = result.total_battery_charge_kwh + result.total_battery_discharge_kwh
            excess = result.total_grid_export_kwh + result.total_curtailed_kwh
            _pdf_kv_table(pdf, [
                ("Solar Production", f"{result.total_solar_kwh:.1f} kWh"),
                ("Grid Purchase", f"{result.total_grid_purchase_kwh:.1f} kWh"),
                ("Battery Usage", f"{battery_usage:.1f} kWh"),
                ("Excess Energy", f"{excess:.1f} kWh"),
            ])

    pdf.add_page()
    if watermark:
        _pdf_watermark(pdf, watermark)
    _pdf_heading(pdf, "Savings & ROI")
    payback = f"{roi['payback_years']:.1f} years" if roi["payback_years"] is not None else "Not within horizon"
    _pdf_kv_table(pdf, [
        ("Estimated Monthly Savings", f"PHP {roi['monthly_savings']:,.2f}"),
        ("Estimated Annual Savings", f"PHP {roi['annual_savings']:,.2f}"),
        ("System Cost", f"PHP {roi['system_cost']:,.2f}"),
        ("Payback Period", payback),
        (f"{len(roi['projection_rows'])}-Year Net Benefit", f"PHP {roi['net_benefit']:,.2f}"),
        ("Return on Investment", f"{roi['roi_pct']:.1f}%"),
    ])

    if roi_chart_image:
        pdf.image(roi_chart_image, w=pdf.epw)
        pdf.ln(4)

    pdf.add_page()
    if watermark:
        _pdf_watermark(pdf, watermark)
    _pdf_heading(pdf, "Financial Projection")
    from fpdf.fonts import FontFace

    headers = ["Year", "Rate", "Grid Cost\n(No Solar)", "Grid Cost\n(Solar)", "Savings", "Maint.",
               "Net Savings", "Cumulative"]
    weights = [0.6, 0.85, 1.3, 1.3, 1.05, 0.85, 1.15, 1.3]
    avail_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_widths = [avail_w * w / sum(weights) for w in weights]

    pdf.set_font("Helvetica", "", 9)
    heading_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=PRIMARY_RGB)
    band_style = FontFace(fill_color=BAND_RGB)
    with pdf.table(col_widths=col_widths, text_align="LEFT", headings_style=heading_style,
                   line_height=6.5, borders_layout="HORIZONTAL_LINES") as table:
        row = table.row()
        for h in headers:
            row.cell(h)
        for i, r in enumerate(roi["projection_rows"]):
            row = table.row(style=band_style if i % 2 == 1 else None)
            row.cell(str(r.year))
            row.cell(f"{r.electricity_rate:.2f}")
            row.cell(f"{r.grid_cost_without_solar:,.0f}")
            row.cell(f"{r.grid_cost_with_solar:,.0f}")
            row.cell(f"{r.electricity_savings:,.0f}")
            row.cell(f"{r.maintenance:,.0f}")
            row.cell(f"{r.net_savings:,.0f}")
            row.cell(f"{r.cumulative_cash_flow:,.0f}")

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTED_RGB)
    pdf.multi_cell(pdf.epw, 4, DISCLAIMER)

    pdf.output(path)


# --- PowerPoint export -------------------------------------------------------

def _set_gradient_bg(slide, hex1: str, hex2: str, angle: float = 45.0) -> None:
    from pptx.dml.color import RGBColor

    bg = slide.background
    bg.fill.gradient()
    stops = bg.fill.gradient_stops
    stops[0].color.rgb = RGBColor.from_string(hex1)
    stops[1].color.rgb = RGBColor.from_string(hex2)
    bg.fill.gradient_angle = angle


def _add_textbox(slide, left, top, width, height, lines):
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Pt(4)
    tf.margin_right = Pt(4)
    for i, (text, size, hex_color, bold) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(6)
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(hex_color)


def _add_card(slide, left, top, width, height, title, value, accent_hex="2B6CB0"):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
    card.line.color.rgb = RGBColor.from_string(accent_hex)
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.margin_left = Pt(14)
    tf.margin_right = Pt(14)
    tf.margin_top = Pt(10)
    p0 = tf.paragraphs[0]
    p0.alignment = PP_ALIGN.LEFT
    r0 = p0.add_run()
    r0.text = title
    r0.font.size = Pt(13)
    r0.font.color.rgb = RGBColor.from_string("6B7684")
    p1 = tf.add_paragraph()
    p1.alignment = PP_ALIGN.LEFT
    p1.space_before = Pt(4)
    r1 = p1.add_run()
    r1.text = value
    r1.font.size = Pt(22)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor.from_string("1F2933")


def _blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def generate_pptx(
    path: str, data: dict, chart_images: dict | None = None, roi_chart_image: str | None = None,
) -> None:
    """chart_images: optional {scenario_name: png_path} (see report_screen.py's
    _render_scenario_chart_png) -- for each scenario present in both this dict and
    data["simulation"]["scenario_results"], adds one slide with that scenario's hourly
    chart image and a summary of its totals underneath, in SCENARIO_ORDER.

    roi_chart_image: optional path to a pre-rendered PNG of the ROI screen's
    cumulative cash-flow chart (see report_screen.py's _render_roi_chart) --
    added as its own slide, right after the Savings & ROI cards slide."""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    client = data["client"]
    consumption = data["consumption"]
    solar = data["solar"]
    battery = data["battery"]
    system_design = data["system_design"]
    simulation = data["simulation"]
    roi = data["roi"]

    # Cover
    slide = _blank_slide(prs)
    _set_gradient_bg(slide, *PPTX_THEME["cover"], angle=45)
    title = data.get("company_name") or "Solar Proposal"
    _add_textbox(slide, Inches(0.8), Inches(2.6), Inches(11), Inches(1.2), [(title, 40, "FFFFFF", True)])
    _add_textbox(
        slide, Inches(0.8), Inches(3.6), Inches(11), Inches(0.8),
        [(f"Solar System Proposal for {client['client_name'] or 'Prospective Client'}", 20, "FFE8B3", False)],
    )
    _add_textbox(slide, Inches(0.8), Inches(4.2), Inches(11), Inches(0.5),
                 [(client["project_date"], 14, "DCE7F2", False)])

    # Client
    slide = _blank_slide(prs)
    _set_gradient_bg(slide, *PPTX_THEME["client"], angle=90)
    _add_textbox(slide, Inches(0.6), Inches(0.4), Inches(9), Inches(0.8), [("Client Profile", 30, "1E4E7F", True)])
    lines = [
        (f"Client: {client['client_name'] or '-'}", 16, "1F2933", True),
        (f"Location: {client['project_location'] or '-'}", 14, "1F2933", False),
        (f"Contact: {client['contact_number'] or '-'}", 14, "1F2933", False),
        (f"Email: {client['email'] or '-'}", 14, "1F2933", False),
        (f"Country: {client.get('country') or '-'}", 14, "1F2933", False),
    ]
    _add_textbox(slide, Inches(0.6), Inches(1.4), Inches(5.5), Inches(3), lines)
    cards = [
        ("Monthly Consumption", f"{client['monthly_kwh']:.0f} kWh"),
        ("Day / Night Split", f"{client['daytime_pct']}% / {client['nighttime_pct']}%"),
        ("Daily Consumption", f"{consumption['daily_kwh']:.2f} kWh"),
        ("Peak Hourly Load", f"{consumption['peak_kwh']:.2f} kWh"),
    ]
    top = 1.4
    for card_title, value in cards:
        _add_card(slide, Inches(6.6), Inches(top), Inches(6.0), Inches(0.95), card_title, value, "2B6CB0")
        top += 1.15

    # Recommended system
    slide = _blank_slide(prs)
    _set_gradient_bg(slide, *PPTX_THEME["system"], angle=45)
    _add_textbox(slide, Inches(0.6), Inches(0.4), Inches(9), Inches(0.8), [("Recommended System", 30, "5A3A00", True)])
    cards = [
        ("Solar Array", f"{solar['total_kw']:.2f} kWp", "matched to inverter rating"),
        ("Battery Storage", f"{battery['total_kwh']:.2f} kWh", f"usable {battery['usable_kwh']:.2f} kWh"),
        ("Inverter", f"{system_design['rated_power_kw']:.2f} kW", f"efficiency {system_design['efficiency_pct']:.0f}%"),
    ]
    left = 0.7
    for card_title, value, subtitle in cards:
        _add_card(slide, Inches(left), Inches(1.7), Inches(3.8), Inches(2.4), card_title, value, "5A3A00")
        _add_textbox(slide, Inches(left + 0.2), Inches(3.5), Inches(3.4), Inches(0.5),
                     [(subtitle, 12, "6B7684", False)])
        left += 4.1

    # Weather-scenario simulations -- one slide per scenario, chart on top, summary below.
    if chart_images:
        for name in SCENARIO_ORDER:
            image_path = chart_images.get(name)
            result = simulation["scenario_results"].get(name)
            if not image_path or result is None:
                continue

            theme = PPTX_WEATHER_THEME.get(name, PPTX_THEME["client"])
            slide = _blank_slide(prs)
            _set_gradient_bg(slide, *theme, angle=90)
            _add_textbox(slide, Inches(0.6), Inches(0.35), Inches(9), Inches(0.7),
                         [(f"{name} Day Simulation", 28, "1F2933", True)])
            # Width chosen (not the slide's full 12.1in span) so the chart's own
            # height -- derived from its 1600x700 source aspect ratio -- stays
            # clear of the cards below at y=6.15in, instead of its bottom axis
            # labels running underneath them.
            slide.shapes.add_picture(image_path, Inches(0.6), Inches(1.15), width=Inches(11.0))

            battery_usage = result.total_battery_charge_kwh + result.total_battery_discharge_kwh
            excess = result.total_grid_export_kwh + result.total_curtailed_kwh
            cards = [
                ("Solar Production", f"{result.total_solar_kwh:.1f} kWh"),
                ("Grid Purchase", f"{result.total_grid_purchase_kwh:.1f} kWh"),
                ("Battery Usage", f"{battery_usage:.1f} kWh"),
                ("Excess Energy", f"{excess:.1f} kWh"),
            ]
            left = 0.6
            for card_title, value in cards:
                _add_card(slide, Inches(left), Inches(6.15), Inches(2.95), Inches(1.05),
                          card_title, value, theme[1])
                left += 3.15

    # Savings
    slide = _blank_slide(prs)
    _set_gradient_bg(slide, *PPTX_THEME["savings"], angle=45)
    _add_textbox(slide, Inches(0.6), Inches(0.4), Inches(9), Inches(0.8), [("Savings & ROI", 30, "FFFFFF", True)])
    payback = f"{roi['payback_years']:.1f} years" if roi["payback_years"] is not None else "Not within horizon"
    cards = [
        ("Monthly Savings", f"PHP {roi['monthly_savings']:,.0f}"),
        ("Annual Savings", f"PHP {roi['annual_savings']:,.0f}"),
        ("Payback Period", payback),
        ("Net Benefit", f"PHP {roi['net_benefit']:,.0f}"),
        ("Return on Investment", f"{roi['roi_pct']:.1f}%"),
    ]
    top = 1.5
    for card_title, value in cards:
        _add_card(slide, Inches(0.7), Inches(top), Inches(6.0), Inches(0.95), card_title, value, "2F9E44")
        top += 1.1

    # Cumulative cash-flow chart -- its own slide so the ROI trend line is visible
    # (the following photo slide covers the headline numbers, not the trend itself).
    if roi_chart_image:
        slide = _blank_slide(prs)
        _set_gradient_bg(slide, *PPTX_THEME["savings"], angle=45)
        _add_textbox(slide, Inches(0.6), Inches(0.35), Inches(9), Inches(0.7),
                     [("Cumulative Cash Flow", 28, "FFFFFF", True)])
        slide.shapes.add_picture(roi_chart_image, Inches(0.6), Inches(1.15), width=Inches(12.1))

    # Savings summary -- full-bleed photo background with the headline numbers
    # overlaid as cards (a data chart here didn't read well against a themed
    # slide background; a photo + the key figures reads better as a closer).
    slide = _blank_slide(prs)
    slide.shapes.add_picture(ROI_SLIDE_PHOTO, 0, 0, width=prs.slide_width, height=prs.slide_height)
    _add_card(slide, Inches(0.6), Inches(6.15), Inches(3.85), Inches(1.05),
               "System Cost", f"PHP {roi['system_cost']:,.0f}", "2F9E44")
    _add_card(slide, Inches(4.65), Inches(6.15), Inches(3.85), Inches(1.05),
               "Payback Period", payback, "2F9E44")
    _add_card(slide, Inches(8.7), Inches(6.15), Inches(3.85), Inches(1.05),
               f"{len(roi['projection_rows'])}-Year Net Benefit", f"PHP {roi['net_benefit']:,.0f}", "2F9E44")

    # Closing / disclaimer
    slide = _blank_slide(prs)
    _set_gradient_bg(slide, *PPTX_THEME["closing"], angle=45)
    _add_textbox(slide, Inches(0.8), Inches(1.0), Inches(11), Inches(0.8), [("Thank You", 32, "FFFFFF", True)])
    _add_textbox(slide, Inches(0.8), Inches(2.0), Inches(11), Inches(3), [(DISCLAIMER, 12, "DCE7F2", False)])

    prs.save(path)
