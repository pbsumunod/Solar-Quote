from types import SimpleNamespace

from logic.reports import generate_pdf, generate_pptx


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
