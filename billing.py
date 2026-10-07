"""Google Play Billing 9.x integration with resumable, bounded entitlements.

Purchase launch uses Android's UI thread; callbacks return to Kivy. Only a
successful complete query may revoke access. An optional server verifies Play
tokens and returns signed, token-bound offline entitlements (billing_config.py).
"""

import json
import logging
import re
import secrets
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from kivy.utils import platform

import billing_config as config
import internet_time
from billing_entitlements import verify_entitlement
from network_utils import tls_context

log = logging.getLogger(__name__)
PRODUCT_ID_MONTHLY = "solarquote_pro_monthly"
PRODUCT_ID_YEARLY = "solarquote_pro_yearly"
TRIAL_DAYS = 7
_SUBSCRIPTION_PRODUCTS = [PRODUCT_ID_MONTHLY, PRODUCT_ID_YEARLY]
_RESPONSE_OK = 0
_PURCHASED = 1


def _period_label(period):
    match = re.fullmatch(r"P(\d+)([DWMY])", period)
    if not match:
        return "the period shown in Google Play"
    count = int(match[1])
    unit = {"D": "day", "W": "week", "M": "month", "Y": "year"}[match[2]]
    return f"{count} {unit}{'' if count == 1 else 's'}"


class BillingManager:
    def __init__(self):
        self._billing_client = None
        self._activity = None
        self._is_pro = False
        self._initialized = False
        self._connected = False
        self._ever_connected = False
        self._connecting = False
        self._closed = False
        self._purchase_query_seq = 0
        self._product_query_seq = 0
        self._purchase_generation = 0
        self._product_details = {}
        self._listeners = {}
        self._ack_inflight = set()
        self._timers = set()
        self._expiry_event = None
        self._state = None
        self._state_lock = threading.RLock()
        self.on_tier_changed = None

    def _state_path(self):
        from db import database
        if database.DB_PATH is None:
            raise RuntimeError("Configure database before billing")
        return Path(database.DB_PATH).parent / "billing_state.json"

    def _now(self):
        now = int(internet_time.utcnow().timestamp())
        with self._state_lock:
            if self._state is not None:
                now = max(now, int(self._state.get("last_seen", 0)))
                self._state["last_seen"] = now
        return now

    def _load_state(self):
        with self._state_lock:
            if self._state is not None:
                return
            try:
                state = json.loads(self._state_path().read_text(encoding="utf-8"))
                if not isinstance(state, dict) or not isinstance(state.get("pending_acks", {}), dict):
                    raise ValueError("Invalid billing state")
                if any(key in state and type(state[key]) is not int
                       for key in ("valid_until", "last_seen")):
                    raise ValueError("Invalid billing timestamps")
                state.setdefault("pending_acks", {})
                self._state = state
            except (OSError, ValueError, TypeError):
                self._state = {"pending_acks": {}, "last_seen": 0}

    def _save_state(self):
        with self._state_lock:
            path = self._state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._state), encoding="utf-8")
            temporary.replace(path)

    def _notify(self):
        if self.on_tier_changed:
            try:
                self.on_tier_changed()
            except Exception:
                log.exception("Could not refresh subscription display")

    def _set_entitlement(self, active):
        from db import database
        previous = database.get_tier() == "pro"
        self._is_pro = bool(active)
        database.set_tier("pro" if active else "free")
        database.set_pro_source("purchase" if active else None)
        database.set_trial_end(None)
        if previous != active:
            self._notify()

    def _load_cached_tier(self):
        from db import database
        self._load_state()
        tier = database.get_tier()
        if tier == "pro" and database.get_pro_source() == "purchase":
            now = self._now()
            expires = self._state.get("valid_until")
            # One migration grace period for legacy local caches, never renewed
            # by a failed query. Existing subscribers keep access while checking.
            if expires is None:
                expires = now + config.OFFLINE_GRACE_SECONDS
                with self._state_lock:
                    self._state["valid_until"] = expires
                    self._save_state()
            active = now < expires
            if config.BACKEND_URL and self._state.get("signed_entitlement"):
                try:
                    claims = self._verify_signed(self._state["signed_entitlement"],
                                                 self._state.get("purchase_token", ""))
                    active = active and claims["active"]
                except (ValueError, TypeError, KeyError):
                    active = False
            if not active:
                self._set_entitlement(False)
                return
        self._is_pro = tier == "pro"
        self._save_state()

    def initialize(self):
        if self._initialized or self._closed:
            return
        self._load_cached_tier()
        self._initialized = True
        from kivy.clock import Clock
        if self._expiry_event is None:
            self._expiry_event = Clock.schedule_interval(self._check_expiry, 60)
        if platform == "android":
            try:
                self._init_android()
            except Exception:
                self._initialized = False
                log.exception("Billing initialization unavailable")

    def _check_expiry(self, _dt=0):
        if self._closed:
            return False
        self._load_cached_tier()
        internet_time.init()
        return True

    def _ensure_classloader(self):
        from jnius import autoclass
        autoclass("java.lang.Thread").currentThread().setContextClassLoader(self._activity.getClassLoader())

    def _init_android(self):
        from jnius import autoclass
        self._activity = autoclass("org.kivy.android.PythonActivity").mActivity
        self._ensure_classloader()
        client = autoclass("com.android.billingclient.api.BillingClient")
        pending = autoclass("com.android.billingclient.api.PendingPurchasesParams")
        self._listeners["purchases_updated"] = _PurchasesUpdatedListener(self)
        self._billing_client = (client.newBuilder(self._activity)
            .setListener(self._listeners["purchases_updated"])
            .enablePendingPurchases(pending.newBuilder().enableOneTimeProducts().build())
            .enableAutoServiceReconnection().build())
        self._connect()

    def _connect(self):
        if self._closed or self._connecting or not self._billing_client:
            return
        self._connecting = True
        try:
            self._ensure_classloader()
            self._listeners["connect"] = _ConnectListener(self)
            self._billing_client.startConnection(self._listeners["connect"])
        except Exception:
            self._connecting = False
            log.warning("Billing connection unavailable")
        # Release a stalled initial connection so a later resume/user action can retry.
        self._schedule(10, lambda: setattr(self, "_connecting", False))

    def _on_connected(self):
        self._connecting = False
        self._connected = True
        self._ever_connected = True
        self._query_purchases()
        self._query_product_details()
        self._retry_acknowledgements()

    def _on_disconnected(self):
        self._connected = False
        self._connecting = False

    def refresh_on_resume(self):
        if self._closed:
            return
        internet_time.init()
        self._load_cached_tier()
        if platform != "android":
            return
        if not self._billing_client:
            self.initialize()
        elif self._ever_connected:
            # Make the API call even after disconnection: that is what triggers
            # BillingClient's automatic service reconnection.
            self._query_purchases()
            self._query_product_details()
            self._retry_acknowledgements()
        else:
            self._connect()

    def close(self):
        self._closed = True
        if self._expiry_event:
            self._expiry_event.cancel()
        for timer in list(self._timers):
            timer.cancel()
        if self._billing_client:
            try:
                self._billing_client.endConnection()
            except Exception:
                log.warning("Could not close billing connection")
        self._listeners.clear()

    def _schedule(self, delay, fn):
        def run():
            try:
                if not self._closed:
                    fn()
            finally:
                self._timers.discard(timer)
        timer = threading.Timer(delay, run)
        timer.daemon = True
        self._timers.add(timer)
        timer.start()

    def _query_purchases(self, on_complete=None, attempt=0):
        if not self._billing_client:
            self._load_cached_tier()
            if on_complete:
                on_complete(None)
            return
        try:
            self._ensure_classloader()
            from jnius import autoclass
            params = autoclass("com.android.billingclient.api.QueryPurchasesParams").newBuilder().setProductType("subs").build()
            self._purchase_query_seq += 1
            sequence = self._purchase_query_seq
            generation = self._purchase_generation
            key = f"query_{sequence}"
            def result_callback(result, purchases):
                self._listeners.pop(key, None)
                if self._closed or sequence != self._purchase_query_seq:
                    if on_complete:
                        on_complete(None)
                    return
                if result.getResponseCode() in (-1, 2, 6, 12) and attempt < 2:
                    self._schedule(2 ** attempt, lambda: self._query_purchases(on_complete, attempt + 1))
                    return
                # An older snapshot must not undo a purchase completed since the query began.
                if generation != self._purchase_generation:
                    self._query_purchases(on_complete)
                    return
                self._on_purchases_queried(result, purchases, on_complete)
            self._listeners[key] = _PurchasesResponseListener(self, result_callback)
            self._billing_client.queryPurchasesAsync(params, self._listeners[key])
        except Exception:
            if "key" in locals():
                self._listeners.pop(key, None)
            self._load_cached_tier()
            if on_complete:
                on_complete(None)

    def _on_purchases_queried(self, billing_result, purchases_list, on_complete=None):
        if billing_result.getResponseCode() != _RESPONSE_OK:
            self._load_cached_tier()
            if on_complete:
                on_complete(None)
            return
        if config.BACKEND_URL:
            self._process_purchases(purchases_list, on_complete=on_complete)
        else:
            found = self._process_purchases(purchases_list)
            if on_complete:
                on_complete(found)

    def _process_purchases(self, purchases_list, authoritative=True, on_complete=None):
        from db import database
        self._load_state()
        try:
            purchases = []
            if purchases_list is not None:
                for i in range(purchases_list.size()):
                    purchase = purchases_list.get(i)
                    if purchase.getPurchaseState() == _PURCHASED:
                        products = purchase.getProducts()
                        if any(products.get(j) in _SUBSCRIPTION_PRODUCTS for j in range(products.size())):
                            purchases.append(purchase)
        except Exception:
            self._load_cached_tier()
            if on_complete:
                on_complete(None)
            return None
        if purchases:
            with self._state_lock:
                owned_tokens = {purchase.getPurchaseToken() for purchase in purchases}
                acknowledged = {purchase.getPurchaseToken() for purchase in purchases
                                if purchase.isAcknowledged()}
                stale = {token for token in self._state["pending_acks"]
                         if token in acknowledged or (authoritative and token not in owned_tokens)}
                for token in stale:
                    self._state["pending_acks"].pop(token, None)
                if stale:
                    self._save_state()
            self._purchase_generation += 1
            if config.BACKEND_URL:
                generation = self._purchase_generation
                threading.Thread(target=self._verify_purchases,
                    args=(purchases, on_complete, generation), daemon=True).start()
                return None
            self._load_state()
            with self._state_lock:
                self._state["valid_until"] = self._now() + config.OFFLINE_GRACE_SECONDS
                self._save_state()
            self._set_entitlement(True)
            for purchase in purchases:
                if not purchase.isAcknowledged():
                    self._acknowledge(purchase)
            return True
        if authoritative:
            self._purchase_generation += 1
            if database.get_pro_source() == "trial":
                self._load_cached_tier()
            else:
                self._load_state()
                with self._state_lock:
                    self._state.pop("signed_entitlement", None)
                    self._state.pop("purchase_token", None)
                    self._state.pop("valid_until", None)
                    self._state["pending_acks"] = {}
                    self._save_state()
                self._set_entitlement(False)
        if on_complete:
            on_complete(False if authoritative else None)
        return False

    def _verify_signed(self, token, purchase_token, nonce=None):
        claims = verify_entitlement(token, modulus_hex=config.PUBLIC_KEY_MODULUS_HEX,
            exponent=config.PUBLIC_KEY_EXPONENT, audience=config.PACKAGE_NAME,
            purchase_token=purchase_token, now=self._now(),
            max_lifetime=config.OFFLINE_GRACE_SECONDS, nonce=nonce,
            fresh_response=nonce is not None)
        if nonce is not None:
            internet_time.set_verified_time(datetime.fromtimestamp(claims["iat"], timezone.utc))
            with self._state_lock:
                self._state["last_seen"] = claims["iat"]
        return claims

    def _verify_purchases(self, purchases, on_complete=None, generation=None):
        self._load_state()
        results = []
        failed = False
        for purchase in purchases:
            token = purchase.getPurchaseToken()
            nonce = secrets.token_urlsafe(24)
            try:
                if not config.BACKEND_URL.startswith("https://"):
                    raise ValueError("Verification requires HTTPS")
                request = urllib.request.Request(config.BACKEND_URL.rstrip("/") + "/verify",
                    data=json.dumps({"purchase_token": token, "nonce": nonce}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=10, context=tls_context()) as response:
                    signed = json.loads(response.read(32768))["entitlement"]
                claims = self._verify_signed(signed, token, nonce)
                results.append((claims, signed, token, purchase))
            except Exception:
                # Never log tokens, response bodies or service credential errors.
                failed = True
                log.warning("Purchase verification unavailable")
        if self._closed or (generation is not None and generation != self._purchase_generation):
            if on_complete:
                on_complete(None)
            return
        active = [result for result in results if result[0]["active"]]
        if active:
            claims, signed, token, _purchase = max(active, key=lambda item: item[0]["exp"])
            self._load_state()
            with self._state_lock:
                self._state.update(valid_until=claims["exp"], signed_entitlement=signed, purchase_token=token)
                self._save_state()
            self._set_entitlement(True)
            for _, _, _, purchase in active:
                if not purchase.isAcknowledged():
                    self._acknowledge(purchase)
        elif failed:
            self._load_cached_tier()
        else:
            with self._state_lock:
                self._state.pop("signed_entitlement", None)
                self._state.pop("purchase_token", None)
                self._state.pop("valid_until", None)
                self._save_state()
            self._set_entitlement(False)
        if on_complete:
            on_complete(True if active else None if failed else False)

    def _acknowledge(self, purchase):
        self._load_state()
        token = purchase.getPurchaseToken()
        with self._state_lock:
            self._state["pending_acks"].setdefault(token, 0)
            self._save_state()
        self._acknowledge_token(token)

    def _retry_acknowledgements(self):
        self._load_state()
        with self._state_lock:
            tokens = list(self._state["pending_acks"])
        for token in tokens:
            self._acknowledge_token(token)

    def _acknowledge_token(self, token):
        if self._closed or not self._billing_client:
            return
        self._load_state()
        with self._state_lock:
            if token not in self._state["pending_acks"] or token in self._ack_inflight:
                return
            self._ack_inflight.add(token)
        key = f"ack_{token}"
        try:
            self._ensure_classloader()
            from jnius import autoclass
            params = autoclass("com.android.billingclient.api.AcknowledgePurchaseParams").newBuilder().setPurchaseToken(token).build()
            def complete(result):
                self._listeners.pop(key, None)
                with self._state_lock:
                    self._ack_inflight.discard(token)
                    if token not in self._state["pending_acks"]:
                        return  # A newer full restore already reconciled it.
                    if result.getResponseCode() == _RESPONSE_OK:
                        self._state["pending_acks"].pop(token, None)
                    else:
                        attempt = self._state["pending_acks"].get(token, 0) + 1
                        self._state["pending_acks"][token] = attempt
                        # Persistent queue survives process termination. Resume retries.
                        if result.getResponseCode() in (-1, 2, 6, 12) and attempt <= 5:
                            self._schedule(min(300, 2 ** attempt), lambda: self._acknowledge_token(token))
                    self._save_state()
            self._listeners[key] = _AcknowledgeListener(complete)
            self._billing_client.acknowledgePurchase(params, self._listeners[key])
        except Exception:
            self._ack_inflight.discard(token)
            self._listeners.pop(key, None)
            log.warning("Purchase acknowledgement unavailable; queued for retry")
            self._schedule(10, lambda: self._acknowledge_token(token))

    def _query_product_details(self):
        if not self._billing_client or self._closed:
            return
        try:
            self._ensure_classloader()
            from jnius import autoclass
            query = autoclass("com.android.billingclient.api.QueryProductDetailsParams")
            product = autoclass("com.android.billingclient.api.QueryProductDetailsParams$Product")
            products = autoclass("java.util.ArrayList")()
            for product_id in _SUBSCRIPTION_PRODUCTS:
                products.add(product.newBuilder().setProductId(product_id).setProductType("subs").build())
            self._product_query_seq += 1
            sequence = self._product_query_seq
            key = f"products_{sequence}"
            def complete(result, query_result):
                self._listeners.pop(key, None)
                if not self._closed and sequence == self._product_query_seq:
                    self._on_product_details(result, query_result)
            self._listeners[key] = _ProductDetailsResponseListener(self, complete)
            self._billing_client.queryProductDetailsAsync(query.newBuilder().setProductList(products).build(), self._listeners[key])
        except Exception:
            if "key" in locals():
                self._listeners.pop(key, None)
            log.warning("Subscription details unavailable")

    def _on_product_details(self, result, query_result):
        if result.getResponseCode() != _RESPONSE_OK or query_result is None:
            return
        self._product_details = {}
        details_list = query_result.getProductDetailsList()
        for i in range(details_list.size()):
            details = details_list.get(i)
            offers = details.getSubscriptionOfferDetails()
            parsed = []
            if offers is None:
                continue
            for j in range(offers.size()):
                offer = offers.get(j)
                phases = offer.getPricingPhases().getPricingPhaseList()
                if not phases.size():
                    continue
                recurring = phases.get(phases.size() - 1)
                # Only sell the actual monthly/yearly cadence advertised here.
                expected_periods = {"P1M"} if details.getProductId() == PRODUCT_ID_MONTHLY else {"P1Y", "P12M"}
                if recurring.getBillingPeriod() not in expected_periods or recurring.getRecurrenceMode() != 1:
                    continue
                first = phases.get(0)
                trial_period = first.getBillingPeriod() if phases.size() > 1 and first.getPriceAmountMicros() == 0 else None
                parsed.append({"details": details, "offer_token": offer.getOfferToken(),
                    "offer_id": offer.getOfferId(), "formatted_price": recurring.getFormattedPrice(),
                    "micros": recurring.getPriceAmountMicros(), "currency": recurring.getPriceCurrencyCode(),
                    "period": recurring.getBillingPeriod(), "trial_period": trial_period,
                    "phases": [{"price": phases.get(index).getFormattedPrice(),
                        "micros": phases.get(index).getPriceAmountMicros(),
                        "period": phases.get(index).getBillingPeriod(),
                        "cycles": phases.get(index).getBillingCycleCount()}
                        for index in range(phases.size())],
                    "fetched_at": time.monotonic()})
            if parsed:
                # Ordinary Subscribe uses the base plan; Start Trial uses a
                # distinct eligible zero-priced introductory offer.
                selected = next((item for item in parsed if item["offer_id"] is None), parsed[0])
                selected["trial_offer"] = next((item.copy() for item in parsed if item["trial_period"]), None)
                self._product_details[details.getProductId()] = selected

    def _dispatch_launch(self, fn):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(fn)()

    def _deliver_launch(self, callback, reason):
        if callback:
            from kivy.clock import Clock
            Clock.schedule_once(lambda _dt: callback(reason), 0)

    def launch_purchase(self, product_id, on_complete=None, trial_only=False):
        if platform != "android":
            self._deliver_launch(on_complete, "not_android")
            return "not_android"
        if not self._billing_client or not self._activity:
            self.refresh_on_resume()
            self._deliver_launch(on_complete, "not_connected")
            return "not_connected"
        cached = self._product_details.get(product_id)
        if not cached or time.monotonic() - cached["fetched_at"] > 900:
            self._query_product_details()
            self._deliver_launch(on_complete, "product_not_ready")
            return "product_not_ready"
        offer = cached.get("trial_offer") if trial_only else cached
        if not offer:
            self._deliver_launch(on_complete, "trial_unavailable")
            return "trial_unavailable"
        def launch():
            try:
                from jnius import autoclass
                flow = autoclass("com.android.billingclient.api.BillingFlowParams")
                product = autoclass("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams")
                products = autoclass("java.util.ArrayList")()
                products.add(product.newBuilder().setProductDetails(offer["details"]).setOfferToken(offer["offer_token"]).build())
                result = self._billing_client.launchBillingFlow(self._activity, flow.newBuilder().setProductDetailsParamsList(products).build())
                code = result.getResponseCode()
                reason = {0: "", 1: "cancelled", 7: "already_owned", 4: "unavailable", -1: "not_connected"}.get(code, "launch_failed")
                if code == 7:
                    self._query_purchases()
                self._deliver_launch(on_complete, reason)
            except Exception:
                log.warning("Purchase launch unavailable")
                self._deliver_launch(on_complete, "launch_failed")
        try:
            self._dispatch_launch(launch)
            return "launch_pending"
        except Exception:
            self._deliver_launch(on_complete, "launch_failed")
            return "launch_failed"

    def _on_purchases_updated(self, result, purchases):
        if self._closed:
            return
        code = result.getResponseCode()
        if code == _RESPONSE_OK and purchases is not None:
            self._process_purchases(purchases, authoritative=False)
        elif code == 7:
            self._query_purchases()

    def restore_purchases(self, on_complete=None):
        if platform != "android":
            self._load_cached_tier()
            from db import database
            found = self._is_pro and database.get_pro_source() == "purchase"
            if on_complete:
                on_complete(found)
            return found
        if self._billing_client:
            self._query_purchases(on_complete)
        else:
            self.refresh_on_resume()
            if on_complete:
                on_complete(None)
        return None

    def is_pro(self):
        self._load_cached_tier()
        return self._is_pro

    def set_pro(self, value):
        self._is_pro = value
        from db import database
        database.set_tier("pro" if value else "free")

    def start_trial(self):
        if platform == "android":
            raise RuntimeError("Android trials must be purchased through Play")
        from db import database
        if database.get_trial_end():
            return
        database.set_trial_end((database.get_trusted_today() + timedelta(days=TRIAL_DAYS)).isoformat())
        database.set_pro_source("trial")
        self.set_pro(True)

    def has_active_trial(self):
        return self.get_trial_days_left() > 0

    def get_trial_days_left(self):
        from db import database
        try:
            return max(0, (date.fromisoformat(database.get_trial_end()) - database.get_trusted_today()).days)
        except (ValueError, TypeError):
            return 0

    def get_monthly_price(self):
        return self._product_details.get(PRODUCT_ID_MONTHLY, {}).get("formatted_price", "Loading price...")

    def get_yearly_price(self):
        return self._product_details.get(PRODUCT_ID_YEARLY, {}).get("formatted_price", "Loading price...")

    def get_yearly_savings(self):
        monthly = self._product_details.get(PRODUCT_ID_MONTHLY)
        yearly = self._product_details.get(PRODUCT_ID_YEARLY)
        if not monthly or not yearly or monthly["currency"] != yearly["currency"] or monthly["micros"] <= 0:
            return ""
        percentage = round(100 * (1 - yearly["micros"] / (12 * monthly["micros"])))
        return f"Save {percentage}%" if percentage > 0 else ""

    def get_trial_terms(self):
        trial = self._product_details.get(PRODUCT_ID_MONTHLY, {}).get("trial_offer")
        if not trial:
            return None
        terms = []
        for phase in trial["phases"][:-1]:
            duration = _period_label(phase["period"])
            cycles = phase["cycles"]
            if phase["micros"] == 0:
                if cycles > 1:
                    duration = f"{cycles} × {duration}"
                terms.append(f"Free for {duration}")
            else:
                terms.append(f"{phase['price']} every {duration} for {cycles} payment(s)")
        terms.append(f"{trial['formatted_price']} per month, renewing until cancelled")
        return ", then ".join(terms) + "."

# ----------------------------------------------------------------------
# PythonJavaClass listener implementations.
#
# Each of these bridges a Google Play Billing Java interface to Python.
# jnius requires this exact pattern -- __javainterfaces__ naming the
# interface (JNI slash-separated form) and @java_method declaring each
# method's JNI signature -- a plain Python class with matching method names
# does NOT implement a Java interface as far as the JVM/JNI boundary is
# concerned.
#
# __javacontext__ = "app" is equally required and easy to miss: pyjnius's
# own create_proxy_instance() (jnius_proxy.pxi) defaults __javacontext__ to
# "system" when a PythonJavaClass subclass doesn't set it, which builds the
# interface proxy against ClassLoader.getSystemClassLoader() -- a
# classloader with no visibility into third-party, app-bundled classes like
# anything under com.android.billingclient.api.*. Confirmed via `adb
# logcat`: without this, every listener construction below threw
# "java.lang.IllegalArgumentException: interface ... is not visible from
# class loader", and setting the thread's context classloader
# (BillingManager._ensure_classloader()) alone did NOT fix it, because the
# default "system" mode never even reads that -- only "app" mode does
# (Thread.currentThread().getContextClassLoader(), which is exactly what
# _ensure_classloader() sets). Both pieces are required together.
# ----------------------------------------------------------------------

def _billing_result_sig(*rest: str) -> str:
    return f"(Lcom/android/billingclient/api/BillingResult;{''.join(rest)})V"


def _lazy_pyjnius_classes():
    """Build the PythonJavaClass subclasses lazily, inside a function, so
    importing this module on non-Android platforms (desktop dev, tests, CI)
    never touches `jnius`, which only exists inside an Android build."""
    from jnius import PythonJavaClass, java_method

    class ConnectListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/BillingClientStateListener"]
        __javacontext__ = "app"

        def __init__(self, manager):
            super().__init__()
            self._manager = manager

        @java_method(_billing_result_sig())
        def onBillingSetupFinished(self, billing_result):
            if billing_result.getResponseCode() == _RESPONSE_OK:
                self._manager._on_connected()
            else:
                self._manager._connecting = False
                log.warning("Billing setup unavailable")
                self._manager._load_cached_tier()

        @java_method("()V")
        def onBillingServiceDisconnected(self):
            self._manager._on_disconnected()

    class PurchasesUpdatedListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/PurchasesUpdatedListener"]
        __javacontext__ = "app"

        def __init__(self, manager):
            super().__init__()
            self._manager = manager

        @java_method(_billing_result_sig("Ljava/util/List;"))
        def onPurchasesUpdated(self, billing_result, purchases_list):
            self._manager._on_purchases_updated(billing_result, purchases_list)

    class PurchasesResponseListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/PurchasesResponseListener"]
        __javacontext__ = "app"

        def __init__(self, manager, callback):
            super().__init__()
            self._manager = manager
            self._callback = callback

        @java_method(_billing_result_sig("Ljava/util/List;"))
        def onQueryPurchasesResponse(self, billing_result, purchases_list):
            self._callback(billing_result, purchases_list)

    class ProductDetailsResponseListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/ProductDetailsResponseListener"]
        __javacontext__ = "app"

        def __init__(self, manager, callback):
            super().__init__()
            self._manager = manager
            self._callback = callback

        # Billing Library 8.0 changed this callback's second parameter from
        # a plain List<ProductDetails> to a QueryProductDetailsResult
        # wrapper (adds getUnfetchedProductList() alongside
        # getProductDetailsList(), so a query can report which products
        # failed to resolve instead of just silently omitting them) --
        # confirmed against the current API reference, not assumed. The
        # JNI signature has to match the wrapper type or this callback
        # simply never fires.
        @java_method(_billing_result_sig("Lcom/android/billingclient/api/QueryProductDetailsResult;"))
        def onProductDetailsResponse(self, billing_result, query_result):
            self._callback(billing_result, query_result)

    class AcknowledgeListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/AcknowledgePurchaseResponseListener"]
        __javacontext__ = "app"

        def __init__(self, callback):
            super().__init__()
            self._callback = callback

        @java_method(_billing_result_sig())
        def onAcknowledgePurchaseResponse(self, billing_result):
            self._callback(billing_result)

    return {
        "connect": ConnectListener,
        "purchases_updated": PurchasesUpdatedListener,
        "purchases_response": PurchasesResponseListener,
        "product_details_response": ProductDetailsResponseListener,
        "acknowledge": AcknowledgeListener,
    }


_java_classes = None


def _get_java_classes():
    global _java_classes
    if _java_classes is None:
        _java_classes = _lazy_pyjnius_classes()
    return _java_classes


def _ConnectListener(manager):  # noqa: N802 (kept PascalCase to read as a constructor)
    return _get_java_classes()["connect"](manager)


def _PurchasesUpdatedListener(manager):  # noqa: N802
    return _get_java_classes()["purchases_updated"](manager)


def _PurchasesResponseListener(manager, callback):  # noqa: N802
    return _get_java_classes()["purchases_response"](manager, callback)


def _ProductDetailsResponseListener(manager, callback):  # noqa: N802
    return _get_java_classes()["product_details_response"](manager, callback)


def _AcknowledgeListener(callback):  # noqa: N802
    return _get_java_classes()["acknowledge"](callback)
