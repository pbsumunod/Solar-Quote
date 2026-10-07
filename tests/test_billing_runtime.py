import json
import ssl
import sys
import time
from types import SimpleNamespace

import pytest

import billing
import internet_time
from billing import BillingManager, PRODUCT_ID_MONTHLY, PRODUCT_ID_YEARLY
from db import database


class JavaList:
    def __init__(self, values=()):
        self.values = list(values)

    def size(self):
        return len(self.values)

    def get(self, index):
        return self.values[index]

    def add(self, item):
        self.values.append(item)


class Result:
    def __init__(self, code=0):
        self.code = code

    def getResponseCode(self):
        return self.code


class Builder:
    @classmethod
    def newBuilder(cls):
        return cls()

    def build(self):
        return self

    def __getattr__(self, name):
        return lambda *_: self


class Purchase:
    def __init__(self, product=PRODUCT_ID_MONTHLY, token="purchase-token", state=1):
        self.product, self.token, self.state = product, token, state

    def getPurchaseState(self):
        return self.state

    def getProducts(self):
        return JavaList([self.product])

    def getPurchaseToken(self):
        return self.token

    def isAcknowledged(self):
        return False


@pytest.fixture
def manager(tmp_path, monkeypatch):
    database.configure(str(tmp_path))
    database.init_db()
    monkeypatch.setattr(billing.config, "BACKEND_URL", "")
    instance = BillingManager()
    instance._ensure_classloader = lambda: None
    instance._schedule = lambda *_: None
    monkeypatch.setitem(sys.modules, "jnius", SimpleNamespace(
        autoclass=lambda name: JavaList if name == "java.util.ArrayList" else Builder))
    monkeypatch.setattr(billing, "_PurchasesResponseListener", lambda _manager, callback: callback)
    monkeypatch.setattr(billing, "_AcknowledgeListener", lambda callback: callback)
    return instance


def test_pending_and_null_updates_preserve_existing_subscription(manager):
    database.set_tier("pro")
    database.set_pro_source("purchase")
    manager._is_pro = True
    manager._on_purchases_updated(Result(), JavaList([Purchase(state=2)]))
    manager._on_purchases_updated(Result(), None)
    assert database.get_tier() == "pro"


def test_disconnect_allows_restore_api_to_trigger_auto_reconnect(manager, monkeypatch):
    monkeypatch.setattr(billing, "platform", "android")
    calls, outcomes = [], []
    manager._billing_client = SimpleNamespace(queryPurchasesAsync=lambda params, callback: (
        calls.append(params), callback(Result(), JavaList())))
    manager._on_disconnected()
    manager.restore_purchases(outcomes.append)
    assert len(calls) == 1
    assert outcomes == [False]


def test_launch_runs_through_android_dispatch_and_reports_immediate_error(manager, monkeypatch):
    monkeypatch.setattr(billing, "platform", "android")
    manager._activity = object()
    manager._billing_client = SimpleNamespace(launchBillingFlow=lambda *_: Result(4))
    manager._product_details[PRODUCT_ID_MONTHLY] = {
        "details": object(), "offer_token": "base-offer", "fetched_at": time.monotonic()}
    scheduled, results = [], []
    manager._dispatch_launch = scheduled.append
    manager._deliver_launch = lambda callback, reason: callback(reason)
    assert manager.launch_purchase(PRODUCT_ID_MONTHLY, results.append) == "launch_pending"
    assert results == []
    scheduled[0]()
    assert results == ["unavailable"]


def test_cancelled_launch_does_not_grant_entitlement(manager, monkeypatch):
    monkeypatch.setattr(billing, "platform", "android")
    manager._activity = object()
    manager._billing_client = SimpleNamespace(launchBillingFlow=lambda *_: Result(1))
    manager._product_details[PRODUCT_ID_MONTHLY] = {
        "details": object(), "offer_token": "base", "fetched_at": time.monotonic()}
    manager._dispatch_launch = lambda fn: fn()
    results = []
    manager._deliver_launch = lambda callback, reason: callback(reason)
    manager.launch_purchase(PRODUCT_ID_MONTHLY, results.append)
    assert results == ["cancelled"]
    assert database.get_tier() == "free"


def test_all_purchases_are_acknowledged_and_failed_ack_is_persisted(manager):
    calls, retries = [], []
    manager._schedule = lambda delay, fn: retries.append(fn)
    manager._billing_client = SimpleNamespace(acknowledgePurchase=lambda params, callback: (
        calls.append(params), callback(Result(2))))
    manager._process_purchases(JavaList([Purchase(token="monthly-token"),
        Purchase(PRODUCT_ID_YEARLY, "yearly-token")]))
    assert len(calls) == 2
    state = json.loads(manager._state_path().read_text())
    assert set(state["pending_acks"]) == {"monthly-token", "yearly-token"}
    assert len(retries) == 2
    manager._billing_client = SimpleNamespace(acknowledgePurchase=lambda params, callback: callback(Result()))
    for retry in retries:
        retry()
    assert manager._state["pending_acks"] == {}
    assert not manager._ack_inflight


def test_restore_reconciles_ack_queue_when_play_already_acknowledged(manager):
    manager._load_state()
    manager._state["pending_acks"] = {"purchase-token": 2, "expired-token": 3}
    purchase = Purchase()
    purchase.isAcknowledged = lambda: True
    manager._process_purchases(JavaList([purchase]))
    assert manager._state["pending_acks"] == {}
    assert json.loads(manager._state_path().read_text())["pending_acks"] == {}


def test_successful_query_grants_bounded_access_errors_do_not_extend_it(manager, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(manager, "_now", lambda: now)
    manager._acknowledge = lambda *_: None
    manager._process_purchases(JavaList([Purchase()]))
    expiry = manager._state["valid_until"]
    assert expiry == now + billing.config.OFFLINE_GRACE_SECONDS
    now += 100
    manager._on_purchases_queried(Result(2), None)
    assert manager._state["valid_until"] == expiry
    assert database.get_tier() == "pro"
    now = expiry
    manager._load_cached_tier()
    assert database.get_tier() == "free"


def test_legacy_cache_migration_grace_survives_restart_without_extension(manager, monkeypatch):
    database.set_tier("pro")
    database.set_pro_source("purchase")
    monkeypatch.setattr(manager, "_now", lambda: 1800000000)
    manager._load_cached_tier()
    expiry = manager._state["valid_until"]
    second = BillingManager()
    monkeypatch.setattr(second, "_now", lambda: 1800000100)
    second._load_cached_tier()
    assert second._state["valid_until"] == expiry


def test_close_ends_client_and_cancels_scheduled_work(manager):
    calls = []
    manager._billing_client = SimpleNamespace(endConnection=lambda: calls.append("closed"))
    manager._expiry_event = SimpleNamespace(cancel=lambda: calls.append("cancelled"))
    manager.close()
    assert calls == ["cancelled", "closed"]


def test_trial_offer_is_selected_explicitly_and_savings_use_real_prices(manager):
    def phase(price, amount, period):
        return SimpleNamespace(getFormattedPrice=lambda: price,
            getPriceAmountMicros=lambda: amount, getPriceCurrencyCode=lambda: "PHP",
            getBillingPeriod=lambda: period, getBillingCycleCount=lambda: 1,
            getRecurrenceMode=lambda: 1)
    def offer(identifier, token, phases):
        return SimpleNamespace(getOfferId=lambda: identifier, getOfferToken=lambda: token,
            getPricingPhases=lambda: SimpleNamespace(getPricingPhaseList=lambda: JavaList(phases)))
    def details(product, offers):
        return SimpleNamespace(getProductId=lambda: product, getSubscriptionOfferDetails=lambda: JavaList(offers))
    monthly = phase("PHP 300", 300000000, "P1M")
    yearly = phase("PHP 3,240", 3240000000, "P1Y")
    products = JavaList([details(PRODUCT_ID_MONTHLY, [
        offer(None, "paid-base", [monthly]),
        offer("trial", "free-trial", [phase("Free", 0, "P7D"), monthly])]),
        details(PRODUCT_ID_YEARLY, [offer(None, "annual-base", [yearly])])])
    manager._on_product_details(Result(), SimpleNamespace(getProductDetailsList=lambda: products))
    assert manager._product_details[PRODUCT_ID_MONTHLY]["offer_token"] == "paid-base"
    assert manager._product_details[PRODUCT_ID_MONTHLY]["trial_offer"]["offer_token"] == "free-trial"
    assert manager.get_yearly_savings() == "Save 10%"
    assert "7 days" in manager.get_trial_terms()
    products.values[0] = details(PRODUCT_ID_MONTHLY, [offer(None, "paid-base", [monthly])])
    manager._on_product_details(Result(), SimpleNamespace(getProductDetailsList=lambda: products))
    assert manager.get_trial_terms() is None


def test_overlapping_price_queries_keep_listeners_and_ignore_old_results(manager, monkeypatch):
    callbacks, results = [], []
    monkeypatch.setattr(billing, "_ProductDetailsResponseListener", lambda _manager, callback: callback)
    manager._billing_client = SimpleNamespace(queryProductDetailsAsync=lambda _params, callback: callbacks.append(callback))
    manager._on_product_details = lambda _result, details: results.append(details)
    manager._query_product_details()
    manager._query_product_details()
    assert len(manager._listeners) == 2
    callbacks[1](Result(), "current-prices")
    callbacks[0](Result(), "old-prices")
    assert results == ["current-prices"]
    assert manager._listeners == {}


def test_mobile_verification_uses_signed_response_and_keeps_cache_on_network_error(manager, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from backend.service import BillingService
    from datetime import datetime, timezone
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = 1800000000
    expiry = datetime.fromtimestamp(now + 3600, timezone.utc).isoformat()
    backend = BillingService(key, lambda _token: {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "lineItems": [{"productId": PRODUCT_ID_MONTHLY, "expiryTime": expiry}]},
        lambda *_: None, clock=lambda: now)
    monkeypatch.setattr(billing.config, "BACKEND_URL", "https://configured.example")
    monkeypatch.setattr(billing.config, "PUBLIC_KEY_MODULUS_HEX", format(key.public_key().public_numbers().n, "x"))
    monkeypatch.setattr(internet_time, "_anchor_utc", None)
    monkeypatch.setattr(internet_time, "_anchor_monotonic", None)
    manager._acknowledge = lambda *_: None
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def read(self, _limit):
            return self.body
    def verified_response(request, timeout, context):
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.cert_store_stats()["x509_ca"] > 0
        data = json.loads(request.data)
        response = Response()
        response.body = json.dumps({"entitlement": backend.verify(data["purchase_token"], data["nonce"])}).encode()
        return response
    monkeypatch.setattr(billing.urllib.request, "urlopen", verified_response)
    results = []
    manager._verify_purchases([Purchase()], results.append)
    assert results == [True]
    assert database.get_tier() == "pro"
    assert manager._state["valid_until"] == now + 3600
    saved = manager._state["signed_entitlement"]
    def unavailable(*_args, **_kwargs):
        raise OSError("network unavailable")
    monkeypatch.setattr(billing.urllib.request, "urlopen", unavailable)
    manager._verify_purchases([Purchase()], results.append)
    assert results == [True, None]
    assert database.get_tier() == "pro"
    assert manager._state["signed_entitlement"] == saved
    assert manager._state["valid_until"] == now + 3600
