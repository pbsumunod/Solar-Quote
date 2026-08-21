# SolarQuote

Solar system sizing, ROI simulation, and client-ready proposal exports — for installers, on Android.

## What it does

- **Client & consumption intake** — monthly usage, day/night split, hourly load profile.
- **Auto-sized system** — battery capacity and inverter/panel array are picked automatically from fixed spec catalogs (rounded up to the next available size), with a "Show Calculation" view for anyone who wants the underlying math.
- **Weather simulation** — hour-by-hour solar/battery/grid flow across Sunny, Cloudy, and Rainy scenarios, with country-based solar harvest scaling.
- **ROI & payback** — multi-year financial projection with configurable electricity inflation and export rates.
- **Proposal export** — PDF, Excel, CSV, and PowerPoint (with per-scenario chart slides), ready to hand to a client.

## Stack

Kivy + KivyMD, packaged for Android via [Buildozer](https://github.com/kivy/buildozer) / python-for-android. All sizing/financial logic lives in `logic/` as plain Python, independent of the UI layer.

## Building

Buildozer requires Linux (WSL2 on Windows). From a native filesystem path (not `/mnt/c/...`):

```bash
buildozer android debug
```

Produces an installable APK under `bin/`.

## Project layout

```
logic/      Sizing, simulation, financial, and report-generation logic (no Kivy dependency)
screens/    One module per app screen (Client, Consumption, Solar, Battery, System Design, Simulation, ROI, Report)
widgets/    Custom-drawn chart/legend/background widgets
db/         Local SQLite persistence
recipes/    Custom python-for-android build recipes
```
