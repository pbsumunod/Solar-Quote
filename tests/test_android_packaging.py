import struct
import xml.etree.ElementTree as ET

import pytest

from p4a_hooks import before_apk_assemble
from scripts.check_android_artifact import check_elf


def elf(machine=183, alignment=16384):
    data = bytearray(120)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 16, 3)
    struct.pack_into("<H", data, 18, machine)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<I", data, 64, 1)
    struct.pack_into("<Q", data, 112, alignment)
    return data


def test_artifact_check_rejects_host_extensions_and_unaligned_native_libraries():
    assert check_elf(elf(), "arm64-library") == 1
    with pytest.raises(ValueError, match="arm64"):
        check_elf(elf(machine=62), "host-fonttools-extension")
    with pytest.raises(ValueError, match="below 16 KB"):
        check_elf(elf(alignment=4096), "old-native-library")


def test_artifact_check_rejects_truncated_and_nonloadable_elf():
    with pytest.raises(ValueError, match="truncated"):
        check_elf(b"\x7fELF", "broken-library")
    data = elf()
    struct.pack_into("<I", data, 64, 0)
    with pytest.raises(ValueError, match="no ELF LOAD"):
        check_elf(data, "nonloadable-library")


def test_arm64_relocatable_development_objects_do_not_require_load_segments():
    data = elf()
    struct.pack_into("<H", data, 16, 1)
    struct.pack_into("<HH", data, 54, 0, 0)
    assert check_elf(data, "lxml-header-object.o") == 0
    struct.pack_into("<H", data, 18, 62)
    with pytest.raises(ValueError, match="arm64"):
        check_elf(data, "host-object.o")


def test_manifest_hook_is_idempotent_and_disables_transfer_of_private_state(tmp_path, monkeypatch):
    root = tmp_path / "src" / "main"
    root.mkdir(parents=True)
    manifest = root / "AndroidManifest.xml"
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<application android:allowBackup="true"><activity android:name="org.kivy.android.PythonActivity" '
        'android:windowSoftInputMode="adjustPan" /></application></manifest>', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before_apk_assemble(None)
    before_apk_assemble(None)
    application = ET.parse(manifest).getroot().find("application")
    android = "{http://schemas.android.com/apk/res/android}"
    assert application.get(android + "allowBackup") == "false"
    assert application.get(android + "dataExtractionRules") == "@xml/data_extraction_rules"
    assert len(application.findall("provider")) == 1
    assert application.find("activity").get(android + "windowSoftInputMode") == "adjustResize"
