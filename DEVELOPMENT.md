# Development and validation

Install `requirements-dev.txt` in an isolated environment and run `python -m pytest` from the repository root. Tests should use temporary databases/directories; do not point them at a user's application data.

## Quote exports

`logic.reports.report_sections()` provides common metadata, equipment, warnings, and assumptions across PDF, Excel, CSV, and PowerPoint. New financial projection fields belong in `PROJECTION_COLUMNS`. Export data should be an immutable snapshot of all quote steps, plus the app version and generated-at timestamp.

`ReportScreen._export(kind)` is asynchronous. Scheduled main-thread callbacks capture chart images, then a worker performs font subsetting, image flattening, and document generation. Widget mutations/completion messages are scheduled through Kivy's Clock. Runtime harnesses must process frames until `_exporting` is false. Never invoke Share, Email, Save a Copy, purchase, or external app opening unless specifically testing a user-authorized flow.

`generate_atomic()` writes a temporary file beside the final destination and replaces it only after generation succeeds. Capture folders/temporary files are removed on failure. The UI prevents overlapping export jobs. Prior proposals receive distinct filenames rather than being overwritten.

PDF uses static Noto Sans regular/bold plus a Noto Sans SC CJK fallback under SIL OFL 1.1. Do not restore global fontTools stubs: Unicode parsing/subsetting requires the actual library. Preserve complete licenses/source notices in `assets/fonts`. Android's local `recipes/fonttools` builds the pinned fontTools source with `FONTTOOLS_WITH_CYTHON=0`. The flag alone cannot prevent pip from installing a host wheel. Chardet is pinned to the pure Python 5.2.0 release because newer host wheels contain mypyc extensions. Keep these version pins consistent with `requirements-dev.txt`.

## Android build validation

Build with Ubuntu 22.04, Java 17, Buildozer 1.5.0 and Cython 3.0.12. `buildozer.spec` pins the p4a commit, NDK 28c, SDK/build-tools 36, and application dependencies. Preserve `Pillow` capitalization: p4a's version override is case sensitive for this recipe. The local Pillow recipe updates the upstream setup patch for version 12.3 while retaining its cross-compilation behavior and excluding host library/include discovery. Buildozer 1.5 performs user-site pip installs; use a dedicated build user/environment, or an isolated `PYTHONUSERBASE` with a venv that enables user-site packages.

Do not move compiled recipe caches between absolute project paths. Reuse SDK/NDK and source downloads, then rebuild path-dependent recipes in an isolated directory. CI cache keys include the spec, recipes, hook, resources and build workflows.

After assembling an APK or AAB, run `python scripts/check_android_artifact.py <artifact>`. It checks every ARM64 ELF, including extensions inside the compressed Python bundle, and requires 16 KB LOAD alignment. Verify APK ZIP alignment with SDK `zipalign -c -P 16 -v 4`. Release CI additionally verifies the expected signer with strict `jarsigner`, checks a bundletool-generated APK and collects matching unstripped libraries by ELF build ID. Symbols must retain the top-level `arm64-v8a/` directory in the upload ZIP.

Tests inspect Unicode extraction, warnings, capacities, assumptions, financial fields, every-page watermarks, path portability, formula injection handling, and partial-file cleanup. Worker tests check snapshots, off-thread generation, scheduled completion, and cleanup. Device checks remain necessary; a ZIP/PDF signature alone is insufficient.

## Device checks before a release

Check a signed build on supported Android versions and at narrow display widths with a larger system font. Verify keyboard visibility, drafts, project changes, billing lifecycle/offer terms, insets, and equipment warnings. Export each format using Latin extended/CJK names, long addresses, no battery storage, zero capital cost, and a 50-year horizon.

View outputs in PDF/Office apps. Confirm chart legends/units and continuation-page watermarks. From History, test Save a Copy through the document picker, cancellation, low storage, provider permission errors, and deleting only the app copy. Test Share/Email intentionally with disposable projects: they open another app and never send automatically.

The Android Save a Copy activity-result/URI flow cannot be fully exercised by desktop tests. Validate pyjnius byte-array transfer, cloud document providers, and activity recreation on devices. PowerPoint records font families rather than embedding fonts; inspect font substitution in recipient software.

Automatic Android app backup is disabled by the release manifest. User-created JSON backups, reports, device/vendor backups, and previously shared copies have independent lifetimes. Keep the in-app Privacy Policy and public `index.html` consistent when network/storage behavior changes.
