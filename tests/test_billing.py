from datetime import timedelta

from billing import BillingManager
from db import database


class _JavaList:
    def __init__(self, values=()):
        self._values = list(values)

    def size(self):
        return len(self._values)

    def get(self, index):
        return self._values[index]


def _configure_db(tmp_path):
    database.configure(str(tmp_path))
    database.init_db()


def test_empty_play_query_revokes_cached_purchase(tmp_path):
    _configure_db(tmp_path)
    database.set_tier("pro")
    database.set_pro_source("purchase")
    manager = BillingManager()
    manager._is_pro = True
    changes = []
    manager.on_tier_changed = lambda: changes.append(True)

    manager._process_purchases(_JavaList())

    assert manager.is_pro() is False
    assert database.get_tier() == "free"
    assert database.get_pro_source() is None
    assert changes == [True]


def test_empty_play_query_preserves_active_local_trial(tmp_path):
    _configure_db(tmp_path)
    database.set_trial_end(
        (database.get_trusted_today() + timedelta(days=7)).isoformat()
    )
    database.set_pro_source("trial")
    database.set_tier("pro")
    manager = BillingManager()
    manager._is_pro = True

    manager._process_purchases(_JavaList())

    assert manager.is_pro() is True
    assert database.get_tier() == "pro"
    assert database.get_pro_source() == "trial"


def test_restore_callback_waits_for_query_result(tmp_path):
    _configure_db(tmp_path)
    database.set_tier("pro")
    database.set_pro_source("purchase")
    manager = BillingManager()
    manager._is_pro = True
    outcomes = []

    class Result:
        def getResponseCode(self):
            return 0

    manager._on_purchases_queried(Result(), _JavaList(), outcomes.append)

    assert outcomes == [False]
    assert database.get_tier() == "free"


def test_restore_callback_reports_query_failure_without_claiming_success(tmp_path):
    _configure_db(tmp_path)
    database.set_tier("pro")
    database.set_pro_source("purchase")
    manager = BillingManager()
    outcomes = []

    class Result:
        def getResponseCode(self):
            return 3

        def getDebugMessage(self):
            return "Unavailable"

    manager._on_purchases_queried(Result(), None, outcomes.append)

    assert outcomes == [None]
    assert database.get_tier() == "pro"  # preserve cache on transient errors
