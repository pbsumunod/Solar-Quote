# SolarQuote

Solar sizing, hourly energy simulation, financial projections, and client proposal exports for installers in the Philippines. Built with Kivy/KivyMD for Android, with a desktop development workflow.

## Using the app

Enter client consumption, measured peak/starting demand when available, and site details. Review the hourly profile, solar and battery choices, inverter limits, and engineering warnings before comparing weather scenarios and financial assumptions. Equipment selections are estimates until verified against the actual manufacturer's specifications and site conditions.

Inverter selection is automatic: 1, 3, 5, 6, 8, 10, 12, 16, 18, 20, 25, 30, 40 and 50 kW, followed by supported parallel 50 kW configurations up to 500 kW nominal AC capacity. The smallest compatible configuration must satisfy load headroom, entered starting demand, PV capacity, battery voltage and current. Unsupported demand produces a design error instead of an undersized quotation. DC solar capacity is sized separately in 0.1 kWp planning increments.

Battery selection starts at the 24 V class (25.6 V nominal), then 48 V class (51.2 V nominal), then compatible high-voltage series banks. The app selects module counts, voltage envelope and current limits together. With default assumptions, 120 kWh/month and storage enabled selects a 1 kW planning assembly, 1.3 kWp array and one 2.56 kWh / 25.6 V module. The 1 kW reference assembly requires a battery and approved grid transfer arrangement, and cannot export to the grid; a batteryless small client uses the compatible 3 kW hybrid. Higher HP3 models require three-phase service. Product sources, limitations and review date travel with each quote.

Optional site-resource lookup requests NASA POWER data using the coordinates you provide. Roof orientation and shading adjustments are local. Cached resource values and the core quote workflow work offline.
Annual financial energy figures integrate monthly site-resource simulations by calendar days, with weather factors calibrated to the imported all-sky resource. Hardware selection reports inverter/model counts, battery voltage classes and module arrangements, operating current limits, catalog sources, and any planning-only caveats.

Editing coordinates or roof inputs clears the stale resource. Manual peak sun hours remain available offline. Financial projections include panel/battery degradation, replacement intervals and quoted replacement costs, discount rate, NPV and discounted payback. Zero replacement prices exclude those expenses; obtain supplier quotations. Battery replacements are excluded when storage is disabled. Sensitivity compares installed cost and retail tariff ±10% and solar yield ±20%, changing one assumption at a time. Lifetime/yield effects scale first-year displacement and are disclosed approximations.

Projects and recoverable drafts are stored locally. Save completed quotes before switching projects; use backup/import to keep a separate project copy. Backups contain client information and should be handled accordingly.

## Proposals and files

PDF, Excel, CSV, and PowerPoint use the same quote identifier, version, client profile, equipment selection, engineering warnings, and assumptions. Financial tables include replacement costs and discounted cash flows. PDF embeds licensed Noto fonts for Latin extended text, punctuation, the peso sign, and CJK text. PowerPoint uses font family names; the recipient's presentation software may substitute fonts.

Report previews refresh when opened. Exports capture a snapshot, render chart images on the UI thread, and generate documents in a worker. Files are written atomically so failed generation does not leave a partial final proposal. History lists earlier proposals and provides View, Save a Copy, and Delete App Copy. Android also offers user-initiated Share and Email.

Reports initially stay in app-managed storage. Android Save a Copy opens the system document picker so you can choose Downloads or another destination. Deleting a project does not delete its old reports. Deleting an app report does not delete copies saved or shared elsewhere. Exported backups and external copies survive independently of the app.

## Development

Use Python 3.11 for the Android build toolchain; the desktop suite also runs on Python 3.10. Create an isolated environment and install pinned dependencies:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe main.py
```

Run the app from the repository root. Report asset paths also support callers launched from another working directory. See [DEVELOPMENT.md](DEVELOPMENT.md) for validation, report behavior, and release checks.

## Android builds

Buildozer requires Linux or WSL2. Build from a native Linux filesystem rather than `/mnt/c`:

```bash
buildozer android debug
```

The debug APK appears in `bin/`. GitHub Actions defines debug/release builds and test checks. Real fontTools is packaged in pure Python mode; host native extensions must not enter the Android artifact. Font licenses/provenance are in [assets/fonts/README.txt](assets/fonts/README.txt).

Google Play subscriptions require configured products/offers and the deployment's verification setup. See [backend documentation](backend/README.md) for the optional verification service. No client/project data is included in subscription verification.

The app already uses on-device Google Play Billing. Server verification is prepared locally and remains disabled until a deployed endpoint and public signing key are configured. Google Play distribution and developer backend credentials are separate services.

## Project layout

```text
logic/      Equipment, sizing, site resources, simulation, financial, and export logic
screens/    Guided quote workflow and utilities
widgets/    Charts, legends, and weather decoration
db/         Local SQLite projects, drafts, and settings
assets/     Application images and licensed report fonts
backend/    Optional subscription verification service
tests/      Calculation, data lifecycle, billing, and export regression tests
recipes/    Android build recipes
```

All engineering and financial outputs require professional review. Hourly energy averages cannot establish instantaneous equipment or motor-starting demand.
