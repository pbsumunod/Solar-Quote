"""python-for-android build hook (wired in via buildozer.spec's p4a.hook) that
injects a FileProvider <provider> element into the generated AndroidManifest.xml.

Why a hook and not a buildozer.spec option: buildozer.spec's own
android.extra_manifest_xml injects its content directly inside the <manifest>
element, not inside <application> -- and a <provider> is only valid as a child
of <application>. There's no buildozer.spec key that targets the right place,
so this patches the manifest file directly once p4a has generated it.

FileProvider is what lets report_screen.py hand an exported PDF/Excel/CSV/PPTX
to another app (a messaging app, an email client) via Android's share/send
intents -- Android 7+ (API 24+) blocks apps from sharing raw file:// paths with
each other, so the receiving app needs a content:// URI instead, which is what
FileProvider generates. See android_res/file_paths.xml for the directory it's
allowed to serve (the app's external-files directory, where reports are saved).

Authority string must exactly match report_screen.py's `f"{package_name}.fileprovider"`.
"""

import os

FILEPROVIDER_AUTHORITY = "org.solarclientfinder.solarclientfinder.fileprovider"

PROVIDER_XML = f"""
        <provider
            android:name="androidx.core.content.FileProvider"
            android:authorities="{FILEPROVIDER_AUTHORITY}"
            android:exported="false"
            android:grantUriPermissions="true">
            <meta-data
                android:name="android.support.FILE_PROVIDER_PATHS"
                android:resource="@xml/file_paths" />
        </provider>
"""


def before_apk_assemble(toolchain):
    manifest_path = os.path.join("src", "main", "AndroidManifest.xml")
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    if FILEPROVIDER_AUTHORITY in content:
        # The provider may already be present when Buildozer reuses its generated
        # manifest, but the keyboard resize setting still needs to be guaranteed.
        provider_is_present = True
    else:
        provider_is_present = False

    if "</application>" not in content:
        raise RuntimeError(
            "p4a_hooks.py: could not find </application> in AndroidManifest.xml "
            "to inject the FileProvider -- the manifest template may have changed."
        )

    if not provider_is_present:
        content = content.replace("</application>", PROVIDER_XML + "    </application>")

    # Resize Kivy's view when the Android keyboard opens so ScrollView has a
    # smaller viewport to scroll within, instead of the keyboard covering fields.
    if 'android:windowSoftInputMode="adjustResize"' not in content:
        activity = 'android:name="org.kivy.android.PythonActivity"'
        if activity not in content:
            raise RuntimeError(
                "p4a_hooks.py: could not find the Kivy PythonActivity to configure "
                "Android keyboard resizing."
            )
        content = content.replace(
            activity, activity + ' android:windowSoftInputMode="adjustResize"', 1,
        )

    # Apps targeting API 35 (Android 15) get edge-to-edge display enforced by
    # the OS by default -- content draws behind the status bar and
    # navigation bar whether the app asked for it or not, unless it
    # explicitly insets around them. Kivy 2.3/KivyMD 1.2 predate this and
    # don't handle window insets, so without this the whole app draws under
    # the system bars (reads as "full screen", but is really just unpadded
    # content, not a deliberate fullscreen mode). This attribute is Google's
    # documented temporary opt-out for apps targeting SDK 35 specifically --
    # it is not guaranteed to keep working on a future SDK bump, at which
    # point this app will need real inset-handling instead.
    if 'android:windowOptOutEdgeToEdgeEnforcement="true"' not in content:
        activity = 'android:name="org.kivy.android.PythonActivity"'
        if activity not in content:
            raise RuntimeError(
                "p4a_hooks.py: could not find the Kivy PythonActivity to configure "
                "the edge-to-edge opt-out."
            )
        content = content.replace(
            activity, activity + ' android:windowOptOutEdgeToEdgeEnforcement="true"', 1,
        )

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(content)
