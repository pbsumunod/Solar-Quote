from types import SimpleNamespace

from fpdf import FPDF

from logic.reports import _pdf_watermark, _spreadsheet_text, generate_csv, generate_pdf, generate_pptx


def test_spreadsheet_exports_escape_client_formula_text(tmp_path):
    assert _spreadsheet_text(" =HYPERLINK(\"https://example.com\")").startswith("'")
    assert _spreadsheet_text("+SUM(1,2)").startswith("'")
    assert _spreadsheet_text("-1+2").startswith("'")
    assert _spreadsheet_text("@SUM(1,2)").startswith("'")
    assert _spreadsheet_text("María Santos") == "María Santos"
    path = tmp_path / "quote.csv"
    generate_csv(str(path), {"client": {"client_name": "=1+1", "monthly_kwh": 300},
                             "roi": {"system_cost": 1000, "annual_savings": 100,
                                     "payback_years": 10, "projection_rows": []}})
    assert "'=1+1" in path.read_text(encoding="utf-8")


def test_pdf_watermark_does_not_move_the_drawing_cursor():
    # Regression test: rotation()'s local_context() restores graphics state
    # (font, color, etc.) on exit but not the drawing cursor -- set_xy()
    # inside _pdf_watermark left pdf.x/pdf.y at the watermark's coordinates
    # (page center) instead of back where they were, so every element drawn
    # right after a watermarked page -- title, tables, everything -- started
    # from the wrong position, visibly shifting the whole report.
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    before = (pdf.x, pdf.y)

    _pdf_watermark(pdf, "SolarQuote Free")

    assert (pdf.x, pdf.y) == before


def test_generate_pdf_uses_portable_fonttools_implementation(tmp_path):
    projection_row = SimpleNamespace(
        year=1, electricity_rate=14.5, grid_cost_without_solar=20_000,
        grid_cost_with_solar=8_000, electricity_savings=12_000, maintenance=1_000,
        net_savings=11_000, cumulative_cash_flow=11_000,
    )
    data = {
        "client": {
            "client_name": "Jane Doe", "project_location": "Manila", "contact_number": "",
            "email": "", "country": "Philippines", "monthly_kwh": 400,
            "daytime_pct": 70, "nighttime_pct": 30, "project_date": "2026-08-24",
        },
        "consumption": {"daily_kwh": 13.33, "peak_kwh": 1.5},
        "solar": {"total_kw": 4.5},
        "battery": {"total_kwh": 10, "usable_kwh": 8},
        "system_design": {"rated_power_kw": 5, "efficiency_pct": 97, "warnings": []},
        "simulation": {"scenario_results": {}},
        "roi": {
            "monthly_savings": 1_000, "annual_savings": 12_000, "system_cost": 100_000,
            "payback_years": 9.1, "net_benefit": 50_000, "roi_pct": 50,
            "projection_rows": [projection_row],
        },
    }
    output = tmp_path / "proposal.pdf"

    generate_pdf(str(output), data)

    assert output.read_bytes().startswith(b"%PDF")


def test_generate_pdf_with_watermark_does_not_crash(tmp_path):
    # Regression test: fpdf2 2.7.9 (pinned in buildozer.spec) has no
    # save_state()/restore_state()/translate() methods, so the watermark
    # helper crashed with AttributeError on every call -- meaning every
    # free-tier PDF export (the only export format free users are allowed)
    # crashed outright. generate_pdf() without a watermark (the test above)
    # never exercised that code path, which is why it slipped through.
    projection_row = SimpleNamespace(
        year=1, electricity_rate=14.5, grid_cost_without_solar=20_000,
        grid_cost_with_solar=8_000, electricity_savings=12_000, maintenance=1_000,
        net_savings=11_000, cumulative_cash_flow=11_000,
    )
    data = {
        "client": {
            "client_name": "Jane Doe", "project_location": "Manila", "contact_number": "",
            "email": "", "country": "Philippines", "monthly_kwh": 400,
            "daytime_pct": 70, "nighttime_pct": 30, "project_date": "2026-08-24",
        },
        "consumption": {"daily_kwh": 13.33, "peak_kwh": 1.5},
        "solar": {"total_kw": 4.5},
        "battery": {"total_kwh": 10, "usable_kwh": 8},
        "system_design": {"rated_power_kw": 5, "efficiency_pct": 97, "warnings": []},
        "simulation": {"scenario_results": {}},
        "roi": {
            "monthly_savings": 1_000, "annual_savings": 12_000, "system_cost": 100_000,
            "payback_years": 9.1, "net_benefit": 50_000, "roi_pct": 50,
            "projection_rows": [projection_row],
        },
    }
    output = tmp_path / "proposal_free.pdf"

    generate_pdf(str(output), data, watermark="SolarQuote Free")

    assert output.read_bytes().startswith(b"%PDF")


def test_generate_powerpoint_has_a_valid_presentation_package(tmp_path):
    projection_row = SimpleNamespace(
        year=1, electricity_rate=14.5, grid_cost_without_solar=20_000,
        grid_cost_with_solar=8_000, electricity_savings=12_000, maintenance=1_000,
        net_savings=11_000, cumulative_cash_flow=11_000,
    )
    data = {
        "client": {"client_name": "Jane Doe", "project_location": "Manila", "contact_number": "",
                   "email": "", "country": "Philippines", "monthly_kwh": 400,
                   "daytime_pct": 70, "nighttime_pct": 30, "project_date": "2026-08-24"},
        "consumption": {"daily_kwh": 13.33, "peak_kwh": 1.5},
        "solar": {"total_kw": 4.5}, "battery": {"total_kwh": 10, "usable_kwh": 8},
        "system_design": {"rated_power_kw": 5, "efficiency_pct": 97, "warnings": []},
        "simulation": {"scenario_results": {}},
        "roi": {"monthly_savings": 1_000, "annual_savings": 12_000, "system_cost": 100_000,
                "payback_years": 9.1, "net_benefit": 50_000, "roi_pct": 50,
                "projection_rows": [projection_row]},
    }
    output = tmp_path / "proposal.pptx"

    generate_pptx(str(output), data)

    assert output.read_bytes().startswith(b"PK")
