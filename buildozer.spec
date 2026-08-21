[app]
title = Solar Client Finder
package.name = solarclientfinder
package.domain = org.solarclientfinder

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, assets/icon

version = 0.1.0
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.0,kivymd==1.2.0,sqlite3,openpyxl,et_xmlfile,fpdf2==2.7.9,fonttools,defusedxml,pillow,lxml,python-pptx,typing_extensions,plyer

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon/icon.png

p4a.local_recipes = ./recipes

android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.build_tools = 34.0.0

[buildozer]
log_level = 2
warn_on_root = 1
