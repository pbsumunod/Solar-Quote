from types import SimpleNamespace

from screens.client_screen import QUOTE_STEP_SCREENS, restore_quote_steps


def test_restore_refreshes_each_steps_inputs_before_saved_values():
    events = []

    class Screen:
        def __init__(self, name):
            self.name = name

        def on_pre_enter(self):
            events.append((self.name, "refresh"))

        def apply_state(self, data):
            events.append((self.name, "apply", data))

        def on_leave(self):
            events.append((self.name, "leave"))

    screens = {name: Screen(name) for name in QUOTE_STEP_SCREENS}
    app = SimpleNamespace(root=SimpleNamespace(get_screen=screens.__getitem__))
    restore_quote_steps(app, {"solar": {"peak_sun_hours": 5.5}})

    for name in QUOTE_STEP_SCREENS:
        refresh = events.index((name, "refresh"))
        applied = next(i for i, event in enumerate(events) if event[:2] == (name, "apply"))
        assert refresh < applied
    assert events.index(("consumption", "apply", {})) < events.index(("solar", "refresh"))
    assert ("solar", "apply", {"peak_sun_hours": 5.5}) in events
    assert events.index(("simulation", "leave")) < events.index(("roi", "refresh"))


def test_restore_ignores_malformed_step_data():
    applied = []

    class Screen:
        def on_pre_enter(self):
            pass

        def apply_state(self, data):
            applied.append(data)

        def on_leave(self):
            pass

    app = SimpleNamespace(root=SimpleNamespace(get_screen=lambda _name: Screen()))
    restore_quote_steps(app, {"solar": [1, 2, 3]})
    assert applied == [{}] * len(QUOTE_STEP_SCREENS)
