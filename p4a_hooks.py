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
        return  # already injected (buildozer can call hooks more than once)

    if "</application>" not in content:
        raise RuntimeError(
            "p4a_hooks.py: could not find </application> in AndroidManifest.xml "
            "to inject the FileProvider -- the manifest template may have changed."
        )

    content = content.replace("</application>", PROVIDER_XML + "    </application>")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(content)
