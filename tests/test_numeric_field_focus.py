"""Numeric pre-filled fields must be replaced, not appended to, when the user types."""
import os

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

from kivy.clock import Clock

import pytest
from kivymd.app import MDApp

from ui_style import m3_field


@pytest.fixture(autouse=True)
def _kivymd_app():
    app = MDApp()
    yield app


def test_numeric_field_selects_all_on_focus():
    field = m3_field("Monthly (kWh)", input_filter="float")
    field.text = "0.00"
    field.focus = True
    Clock.tick()
    import time
    time.sleep(0.1)
    Clock.tick()
    assert field.selection_text == "0.00"
    field.keyboard_on_textinput(None, "450")
    assert field.text == "450"


def test_plain_text_field_is_not_auto_selected():
    field = m3_field("Client Name")
    field.text = "Test Client"
    field.focus = True
    import time
    time.sleep(0.1)
    Clock.tick()
    assert field.selection_text == ""
