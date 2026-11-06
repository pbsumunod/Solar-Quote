# SolarQuote static + build-level audit, 2026-11-02

## Scope and stack
- Kivy 2.3.1 / KivyMD 1.2.0 app, Python (buildozer + python-for-android, pinned commit), package `org.solarclientfinder.solarclientfinder`, version 1.1.1 (code 1024114), minapi 24, api/target 36, NDK 28c, arm64-v8a only, AAB release.
- Local SQLite DB (`db/database.py`), on-device Google Play Billing (`billing.py`), optional unauthenticated-by-user purchase-verification backend (`backend/server.py`, `backend/service.py`, Supabase Edge adapter in `backend/supabase`). Backend is not deployed (`billing_config.BACKEND_URL` empty).
- Permissions: INTERNET only (`buildozer.spec`). allowBackup=false plus backup_rules/data_extraction_rules excluding everything (`p4a_hooks.py`, `android_res/`). FileProvider exported=false, paths limited to app external-files and private reports.
- Network: NASA POWER (HTTPS), worldtimeapi.org (HTTPS), optional own backend (HTTPS enforced in code); TLS via certifi context.
- Prior audits: none found in the folder (no AUDIT_REPORT/EXECUTIVE_SUMMARY/audit dirs). Only README, DEVELOPMENT.md, docs/implementation-review.txt, which were read as claims.
- Git working tree was clean before my edits.

## Findings
| ID | Severity | Status | Evidence | Fix | Test |
|---|---|---|---|---|---|
| SOLARQUOTE-S-001 | Medium | fixed | `db.import_projects` on a file of 200000 `[` raised uncaught `RecursionError`; the UI handler (`client_screen._import_backup_path`) catches only OSError/ValueError/sqlite3.Error/TypeError, so importing a corrupt/hostile backup would crash the app. Reproduced before the fix. | `db/database.py`: RecursionError converted to ValueError ("not a supported backup") | `tests/test_database.py::test_import_rejects_pathologically_nested_backup_without_crashing` |
| SOLARQUOTE-S-002 | Low | fixed | Touch targets below 48dp: tonal buttons 44dp, outlined 40dp, dialog buttons 44dp, About link rows 40dp | Raised to 48dp in `ui_style.py` and `screens/about_screen.py` (layout only visually verified by headless test suite, not on a device) | existing suite (318 pass) |
| SOLARQUOTE-S-003 | Informational | open | Header icon buttons sit in 40-44dp cells; MDIconButton self-sizes ~48dp so the hit area is likely fine, not verified | none | none |
| SOLARQUOTE-S-004 | Informational | open | Offline entitlement (`tier`, `billing_state.json` with purchase token) lives in app-private plaintext storage; client-only verification is weaker on rooted devices. Documented in backend/README. | Deploy backend + pin key to harden | n/a |
| SOLARQUOTE-S-005 | Informational | open | Ruff full-rule run reports 6 style issues (5 unused imports, 1 lambda assignment); CI only enforces E9,F63,F7,F82 which passes | not changed | n/a |
| SOLARQUOTE-S-006 | Informational | open | `.venv` in the app folder lacks dev requirements (cryptography, pypdf, ruff), so a plain `pytest` fails collection there | I used a scratchpad `--target` dir on PYTHONPATH; app venv untouched | n/a |

No Critical/High defects confirmed.

## Areas reviewed with no defect found
- Manifest/exports: only PythonActivity (launcher) plus non-exported FileProvider; no WebView, no JS bridge, no custom intent filters added by the app (grep: no WebView/setJavaScript).
- Intent handling: ACTION_CREATE_DOCUMENT / OPEN_DOCUMENT / SEND / VIEW with FileProvider URIs and read-grant flags only.
- Cleartext: backend URL must start with https:// (billing.py); all other URLs are https.
- Secrets: grep for key/secret/password patterns found none in source; .gitignore excludes pem/jks/.env/service-account files. No secret values were read or printed.
- Backend signed-entitlement verification (`billing_entitlements.py`): RSA PKCS#1 v1.5 check, audience, token hash, nonce, lifetime limit, key size >= 2048; covered by tests.
- Backup import validation: size cap 20 MB, schema/range validation, atomic transaction, parameterized SQL (column names come from model fields, not input).
- 16 KB page alignment: `scripts/check_android_artifact.py` checks ELF LOAD alignment (script reviewed; not run against a fresh build). Edge-to-edge insets handled in `main.py`; back key handled via `on_keyboard` 27.
- Ads/UMP: N/A, no ads SDK (grep of buildozer.spec requirements and gradle deps: only androidx.core, billing 9.1.0, kotlin-stdlib).

## Backend / API / auth / DB / billing
- Endpoints `/health`, `/verify`, `/notifications` (`backend/server.py`): 16 KB body cap, nonce regex, token length bounds, in-process 30/min rate limit (documented as dev-only), errors return generic JSON without echoing tokens, RTDN requires Google OIDC bearer with audience and service-account email match. No SQL (stateless). Authentication is purchase-token possession only (documented; no user identity). Local only reviewed; the service was not started and no Google calls were made (no credentials, by design).
- Server-side purchase validation exists in code but is disabled until deployed (blocked/pending user). Supabase Deno tests were not run (deno not installed).
- Python backend tests (`tests/test_backend_verification.py`) ran and passed.
- Authorization/RLS, user accounts, payments other than Play Billing: N/A (no user accounts, no remote DB; grep shows no auth/session code beyond entitlement tokens).

## Builds and tests actually run
- `pytest -q` (app venv Python 3.12, deps shim for cryptography/google-auth/pypdf/ruff): 317 passed before edits; 318 passed after the final edit.
- `ruff check --select E9,F63,F7,F82` (CI rule set): passed after the last edit. Full `ruff check`: 6 style findings (S-005).
- `compileall` of app packages: passed.
- Not run: `buildozer android debug` (README: requires Linux/WSL2; not available on macOS host), Android lint, emulator tests (not in this phase), Deno tests, release bundle (existing `bin/*.aab` untouched).

## Not verified
- Android build output, manifest after p4a hook, 16 KB alignment of a new build, runtime appearance of the 48dp changes, real Play Billing flows, deployed backend, dependency CVE scan (no network audit tool run; pinned versions only listed in buildozer.spec/requirements).
- Contrast, TalkBack labels and text-scale behaviour of Kivy widgets: Kivy has no native content descriptions, so TalkBack support is expected to be limited; needs emulator review.


---

# Emulator audit (2026-11-02, Pixel_10a AVD, emulator-5554, Android arm64-v8a, 1080x2424)

Screenshots: `/Users/pamelasumunod/SumClarTech Apps/AUDIT_OTHER_APPS/screens/SolarQuote/`

## Build under test (important caveat)
- `buildozer android debug` cannot run here (macOS host, no Docker daemon/WSL; README requires Linux). A new APK could NOT be built, so edits made in this audit (S-001, S-002, E-002 fix) are **not verified on a device**.
- Tested instead: existing `bin/solarquote-ui-qa-debug.apk` (versionName 1.1.0, code 1024113, built 2026-10-08). It is OLDER than the current source (1.1.1). Findings below apply to that build; where the current source already differs, it is stated. The APK was installed with `install -r` after `pm clear` (the package had not been installed before); nothing else was touched and `bin/` was not modified.

## Checks
| Check | Result | Note |
|---|---|---|
| Build debug APK | blocked | no Linux/Docker for buildozer; used existing 1.1.0 debug APK |
| Install + clean first launch | pass | splash then onboarding ("Plan every solar quote...") then Client Info |
| Full 8-step journey (client, consumption, solar, battery, design, simulation, savings/ROI, report) with synthetic data | pass | 450 kWh/month gives 14.79 kWh/day, matches 450*12/365; 4.5 kWp, 3 kW inverter, 7.68 kWh battery; report preview text consistent |
| Save project | pass | "Saved" dialog; project reloaded after force-stop |
| Export PDF | pass | spinner ~20 s on emulator, then dialog View/Save a copy/Delete app copy/Share |
| Share | pass | system chooser shown with the PDF; Back returns to app dialog |
| Export Excel/CSV/PowerPoint, View, Save a copy, Report History | not-run | only PDF + Share exercised |
| Paywall / upgrade / purchase | not-run | footer shows "Free" tier; no real purchase attempted (no test mode used) |
| Runtime permissions grant/deny | N/A | manifest requests INTERNET only (verified with aapt2 dump badging); nothing to grant/revoke |
| HOME and relaunch | pass with caveat | see SOLARQUOTE-E-003 |
| Force-stop and relaunch (state kept) | pass | saved project and client name restored; app returns to step 1 not the last step |
| Rotation | pass | app is portrait locked (SDL hint Portrait); stays portrait when user_rotation=1 |
| Back at root | pass | exits app normally; draft restored on relaunch ("(draft ...)" project) |
| Back at deeper levels / step back buttons | partial | header back arrow and Back buttons seen; not individually walked |
| Font scale 1.3 / 1.0 | fail (low) | SOLARQUOTE-E-004 |
| Small screen 720x1280 @280dpi | pass | layout adapts, header wraps to two lines, nothing clipped in the view checked (step 1 only) |
| Dark mode | informational | SOLARQUOTE-E-005, app stays light |
| Airplane mode on/off | pass | step 1 usable offline, no crash; internet-time logs "unavailable; keeping last UTC estimate" |
| am kill / process death | partial | process was foreground so `am kill` did not kill it (verified via pid log); force-stop relaunch covers cold-start state restore |
| logcat own-process FATAL/ANR/StrictMode | see below | no Java FATAL EXCEPTION, no ANR, no StrictMode; one native abort during monkey |
| Monkey seed 11, 3000 events | FAIL | aborted at event 379, see SOLARQUOTE-E-001 |
| Monkey seed 23, 3000 events | pass | all 3000 events injected; process exits seen were normal back-key exits ("Leaving application") restarted by monkey |
| Unit tests after fix | pass (with env gaps) | 271 passed, 1 failed (`test_mobile_verification...` needs `cryptography`, missing from app .venv, pre-existing S-006), `test_backend_verification.py` and `test_report_contents.py` cannot be collected for the same reason |
| Android lint / release bundle | not-run | cannot build here; existing `bin/*.aab` untouched |

Note on emulator noise: `android.hardwar` SIGABRTs in logcat are the emulator graphics HAL, not the app, and are ignored.

## Findings
| ID | Severity | Status | Evidence | Fix / regression test |
|---|---|---|---|---|
| SOLARQUOTE-E-001 | Medium (risk, 1 repro) | open | Monkey seed 11 aborted the app process at event 379: Python `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0` raised from `kivy/core/window/_window_sdl2.pyx poll` (Kivy 2.3.1 SDL2 event decode), followed by ART `attempting to detach while still running code` abort (SIGABRT in SDLActivity thread, pid 9723). The error arises inside the Kivy/SDL native event loop, not app code; trigger is random injected key/text input. Not reproduced by normal typing. | Cannot be caught from app code without patching Kivy; not changed. Needs a repro on a real IME and possibly a Kivy/SDL2 recipe update. Re-run seed 11 on a rebuilt APK. |
| SOLARQUOTE-E-002 | High (usability/correctness) | fixed in source, device unverified | Numeric fields are pre-filled ("0.00", "14.50"). Typing 450 into Monthly (kWh) produced `0.00450`, i.e. a silent 0.0045 kWh (evidence: 09_ime_hidden.png). A quote would be computed from a wrong value unless the user clears the field. | `ui_style.m3_field` now selects all text on focus for `float`/`int` fields so the first keystroke replaces the value. Regression test `tests/test_numeric_field_focus.py` (fails without the fix, passes with it). Needs rebuild and device recheck. |
| SOLARQUOTE-E-003 | Medium (intermittent) | open | After HOME then relaunch (monkey launcher intent, 2 s in background so onStop ran) the screen stayed fully black for 30+ s, did not recover by tap, swipe or rotation (30_home_relaunch.png, 32b.png); Python main loop was alive (on_resume ran, SDL surfaceCreated logged, no exception). A second HOME then `am start` after 3 s resumed correctly (39_swipe.png), and notification-shade pause/resume was fine. Likely the Kivy/SDL GL surface not being redrawn after the surface is recreated; may be emulator SwiftShader specific. | Not changed (cannot be separated from emulator GL behaviour without a real device). Verify on a physical device. |
| SOLARQUOTE-E-004 | Low (accessibility) | open | With system font scale 1.3 only the system status bar text grew; app text size was unchanged (41_font13.png vs 40_dark.png). The app ignores user text-size settings. | Design decision (Kivy sp scaling); not changed. |
| SOLARQUOTE-E-005 | Informational | open | `cmd uimode night yes` leaves the app in its light theme (no dark theme, 40_dark.png). Acceptable, light theme is consistent and readable. | none |
| SOLARQUOTE-E-006 | Informational | open | Keyboard overlap: in the 1.1.0 APK the focused Monthly (kWh) field was hidden behind the keyboard with no scroll (08_kwh_typed.png). Current source already sets `Window.softinput_mode = "resize"` and `ui_style.keep_focused_field_visible`, so this is probably already fixed in 1.1.1 but unverified. | none; re-check on a rebuilt APK |
| SOLARQUOTE-E-007 | Informational | open | Payback/ROI show N/A and the report says "Payback: Not within horizon" while "25-Year Net Benefit" equals total savings, because no system cost was entered in the flow I used (no installed-cost input found in the 8 steps). Possible product wording issue; not changed because it is a business decision. Also the Savings chart right-axis labels ("1,964,714") are clipped at the screen edge and the design-check list shows a red cross icon for the standing "planning estimate" disclaimer. | none |
| SOLARQUOTE-E-008 | Informational | open | First launch logs a handled `shutil.Error ... Permission denied: .kivy/icon` (Kivy copying its icon dir); harmless, app starts. Also `hid_init` receiver-flag warning from SDL HIDAPI (non-fatal). | none |

Static findings S-001 and S-002 remain "fixed in source, not device-verified" for the reason in the caveat above.

## Not verified
- Anything on current 1.1.1 source on a device (no Android build possible here), including the 48dp touch-target change and the E-002 fix.
- Real device behaviour, real Google Play Billing / paywall / purchase flows, backend verification, TalkBack, real ads (none in this app), real file Save-a-copy / View with external apps, Excel/CSV/PowerPoint exports, Report History, step-by-step back navigation, large-data/edge input (negative or huge numbers).
- Dark mode contrast beyond "app stays light", and small-screen layout beyond step 1.

## State reset
wm size/density reset to 1080x2424/420, font_scale 1.0, airplane off, user_rotation 0 with auto-rotate on, uimode night no. The app (org.solarclientfinder.solarclientfinder) was left installed on emulator-5554, since it was not installed before; a test PDF and a saved "Test Client" project exist only in its private storage.

## Process note
I briefly ran `git stash` and immediately `git stash pop` in this folder; the working tree (including the static-audit edits) was restored intact (verified with `git status`).


---

# Round 2 fixes (2026-11-04)

## Fixed
- SOLARQUOTE-S-005 (style lint): removed 5 unused imports (`screens/about_screen.py` tonal_button, `screens/simulation_screen.py` BoxLayout, `ui_style.py` date and MDFillRoundFlatIconButton; one more auto-fixed by ruff) and replaced the lambda assignment in `p4a_hooks.py` with a `def attribute(name)`. Evidence: `ruff check . --exclude .venv` (ruff installed into a scratchpad --target dir, app venv untouched) now reports "All checks passed!"; `pytest -q` 320 passed (318 before + tests added earlier in the session), 1 warning.
- SOLARQUOTE-S-006 (dev env): no repo change needed; dev dependencies (cryptography, pypdf, google-auth, ruff) were supplied via scratchpad PYTHONPATH; the previously uncollectable backend/report tests now run and pass in that full 320-test run.

## Skipped
- S-003: needs real-device hit-area check.
- S-004: needs backend deployment and key pinning (owner/hosting).
- E-001: native Kivy/SDL2 abort, needs recipe/Kivy update and real-IME repro.
- E-003: black screen after HOME, needs a real device (possibly emulator GL only).
- E-004 (font scale) and E-005 (dark theme): design decisions.
- E-006: probably already fixed in source (softinput resize); needs rebuilt APK.
- E-007: payback/installed-cost wording is a product decision.
- No APK build possible: buildozer requires Linux/WSL2 (not available on this macOS host); no Android build or lint run.
