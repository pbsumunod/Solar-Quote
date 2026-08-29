[app]
title = SolarQuote
package.name = solarclientfinder
package.domain = org.solarclientfinder

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, assets/icon, assets/splash
source.exclude_patterns = p4a_hooks.py

# versionName (cosmetic, shown to users -- bump however you like)
version = 0.1.5

# versionCode (invisible to users, but must strictly increase on EVERY
# upload to Play Console, across every track, forever -- once a number is
# used it can never be reused, even for a deleted release). Left unset,
# python-for-android auto-derives one from `version` above, which is what
# produced a collision here: the API-34 and API-35 builds both had
# version=0.1.0, so both got the identical auto-derived versionCode, and
# Play Console rejected the second upload as a dupe.
# Bump this by at least 1 before every new build you intend to upload
# anywhere in Play Console, regardless of what `version` says. Starting at
# 1024101, not 1: Play Console's error already told us 1024100 is the
# highest one it's seen so far (p4a's auto-derived code, used by the
# API-34 build you already uploaded), and it will reject anything at or
# below that -- this is the smallest value that clears it.
android.numeric_version = 1024105
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.0,kivymd==1.2.0,sqlite3,openpyxl,et_xmlfile,fpdf2==2.7.9,fonttools,defusedxml,pillow,lxml,python-pptx,typing_extensions,plyer

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon/icon.png
presplash.filename = %(source.dir)s/assets/splash/logo_splash.png
android.presplash_color = #FDFCF8

p4a.local_recipes = ./recipes

# Play Console requires new/updated apps to target a recent API level (35 as
# of this build) -- it flags anything older as a submission-blocking error,
# not just a warning. This is a Play policy floor, not a hard requirement of
# the code itself, so it moves up roughly yearly; re-check Play Console's
# error message (it names the current minimum) if this ever gets flagged
# again in the future.
android.api = 35
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.build_tools = 35.0.0
android.enable_androidx = True
p4a.hook = ./p4a_hooks.py
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
android.res_xml = android_res/file_paths.xml

# Play Console requires an Android App Bundle (.aab) for new app uploads, not
# a raw .apk (Google stopped accepting .apk for new apps in Aug 2021). This
# only affects `buildozer android release`, signed for Play Console -- the
# debug builds used for direct-install testing (see .github/workflows/
# build-apk.yml) are unaffected and stay .apk.
android.release_artifact = aab

[buildozer]
log_level = 2
warn_on_root = 0
