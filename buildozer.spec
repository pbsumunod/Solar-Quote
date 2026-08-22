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
android.gradle_dependencies = androidx.core:core:1.12.0
android.res_xml = android_res/file_paths.xml

[buildozer]
log_level = 2
warn_on_root = 1
