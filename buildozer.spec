[app]
title = SolarQuote
package.name = solarclientfinder
package.domain = org.solarclientfinder

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, assets/icon, assets/splash
source.exclude_patterns = p4a_hooks.py

version = 0.1.0
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.0,kivymd==1.2.0,sqlite3,openpyxl,et_xmlfile,fpdf2==2.7.9,fonttools,defusedxml,pillow,lxml,python-pptx,typing_extensions,plyer

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon/icon.png
presplash.filename = %(source.dir)s/assets/splash/logo_splash.png
android.presplash_color = #FDFCF8

p4a.local_recipes = ./recipes

android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.build_tools = 34.0.0
android.enable_androidx = True
p4a.hook = ./p4a_hooks.py
# com.android.billingclient:billing is Google Play Billing Library, used by
# billing.py for Pro subscriptions -- it was missing entirely before, so
# every autoclass("com.android.billingclient...") call in that file would
# have thrown ClassNotFoundException at runtime (caught there, so it failed
# quiet rather than crashing, but no purchase could ever have gone through).
# Check https://developer.android.com/google/play/billing/release-notes for
# a newer version before this one goes stale -- Google has changed this
# library's API shape across majors (billing.py targets the 6.x,
# ProductDetails-based API; the older SkuDetails-based API is deprecated).
android.gradle_dependencies = androidx.core:core:1.12.0,com.android.billingclient:billing:6.2.1
android.res_xml = android_res/file_paths.xml

[buildozer]
log_level = 2
warn_on_root = 0
