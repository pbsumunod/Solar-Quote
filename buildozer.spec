[app]
title = SolarQuote
package.name = solarclientfinder
package.domain = org.solarclientfinder

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt
source.exclude_dirs = tests, backend, scripts, recipes, docs, assets/icon, assets/splash, assets/store_screenshots
source.exclude_patterns = p4a_hooks.py, assets/feature_graphic.png, assets/SolarQuote_Icon_512x512.png

# User-visible version for this release.
version = 1.1.1

# Explicit versionCode increases the previous repository value, 1024113.
# Increase it for each subsequent Play upload, across all release tracks.
android.numeric_version = 1024114
requirements = certifi==2026.7.22,chardet==5.2.0,python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,kivymd==1.2.0,sqlite3,openpyxl==3.1.5,et_xmlfile==2.0.0,fpdf2==2.7.9,fonttools==4.65.0,defusedxml==0.7.1,Pillow==12.3.0,lxml==5.2.2,python-pptx==1.0.2,typing_extensions==4.16.0,plyer==2.1.0

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon/icon.png
presplash.filename = %(source.dir)s/assets/splash/logo_splash.png
android.presplash_color = #FDFCF8

p4a.local_recipes = ./recipes
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831

# Explicit target API; review current Play target-API policy for each release.
android.api = 36
android.minapi = 24
# NDK r28c emits 16 KB-aligned native libraries by default, required by
# Google Play for 64-bit apps targeting Android 15/API 35 and higher.
android.ndk = 28c
android.archs = arm64-v8a
android.build_tools = 36.0.0
android.enable_androidx = True
android.permissions = INTERNET
android.allow_backup = False
p4a.hook = ./p4a_hooks.py
# Retain DWARF data during the release build so CI can create the native
# debug-symbol archive that Google Play uses to symbolicate crash reports.
p4a.extra_args = --with-debug-symbols
# com.android.billingclient:billing is Google Play Billing Library, used by
# billing.py for Pro subscriptions. Was pinned to 6.2.1 -- which does NOT
# have PendingPurchasesParams (that class was introduced in 7.0.0), but
# billing.py's enablePendingPurchases() call requires it. That mismatch
# produced a runtime ClassNotFoundException on-device (caught, so it failed
# quiet as "Could not connect to Google Play Billing" rather than crashing,
# confirmed via `adb logcat`) -- every purchase attempt was silently DOA.
# Bumped to 9.1.0: confirmed via Android's Billing Library release notes
# that Google requires version 8+ for all new apps/updates by Aug 31, 2026,
# and cross-checked every API billing.py uses against the current reference
# docs at this version (see billing.py's own comments on
# ProductDetailsResponseListener specifically, which changed shape in 8.0).
# Check https://developer.android.com/google/play/billing/release-notes
# before bumping this further -- past changes have altered method
# signatures, not just added new ones.
#
# The kotlin-stdlib-jdk7/jdk8 pins below fix a Gradle "Duplicate class"
# failure that Billing Library 9.1.0 introduced: kotlin-stdlib-jdk7/jdk8
# were separate artifacts before Kotlin 1.8, merged into plain kotlin-stdlib
# in 1.8+ (the split artifacts still exist post-1.8, but only as
# near-empty compatibility stubs). Billing 9.1.0 pulls kotlin-stdlib:1.8.22
# directly, but something else in the dependency graph pulls the old
# kotlin-stdlib-jdk7/jdk8:1.6.21 split artifacts, which still contain the
# real (now-duplicated) classes. Pinning these to a matching 1.8.x version
# lets Gradle's ordinary highest-version-wins resolution upgrade that old
# reference to the harmless post-merge stub instead.
android.gradle_dependencies = androidx.core:core:1.12.0,com.android.billingclient:billing:9.1.0,org.jetbrains.kotlin:kotlin-stdlib-jdk7:1.8.22,org.jetbrains.kotlin:kotlin-stdlib-jdk8:1.8.22
android.res_xml = android_res/file_paths.xml, android_res/backup_rules.xml, android_res/data_extraction_rules.xml

# Play Console requires an Android App Bundle (.aab) for new app uploads, not
# a raw .apk (Google stopped accepting .apk for new apps in Aug 2021). This
# only affects `buildozer android release`, signed for Play Console -- the
# debug builds used for direct-install testing (see .github/workflows/
# build-apk.yml) are unaffected and stay .apk.
android.release_artifact = aab

[buildozer]
log_level = 2
warn_on_root = 0
