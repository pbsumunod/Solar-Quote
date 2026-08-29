"""Google Play Billing integration for SolarQuote Pro subscriptions.

Uses the Google Play Billing Library (via pyjnius) to query, purchase, and
restore subscriptions. On Android, subscriptions are tied to the Google
account used at purchase time -- no in-app login is needed. On reinstall,
queryPurchasesAsync() restores the active subscription from Google Play.

Falls back gracefully on non-Android platforms or when billing is unavailable
-- every Android call is wrapped so a billing failure never crashes the app,
it just leaves the user on whatever tier database.get_tier() already knows
about (see db/database.py's trial-aware logic).

Two things a previous version of this file got wrong, worth calling out since
they're easy to get wrong again:

1. Google Play Billing Library callback interfaces (BillingClientStateListener,
   PurchasesUpdatedListener, etc.) are Java interfaces. pyjnius does NOT let a
   plain Python class satisfy one just by having same-named methods -- Java's
   type system has no idea what to do with a bare Python object passed where
   it expects a `BillingClientStateListener` instance. Each listener here is a
   `jnius.PythonJavaClass` subclass declaring `__javainterfaces__` and
   `@java_method(...)` signatures, which is what actually lets pyjnius build a
   JNI-visible proxy implementing the interface. A previous version used plain
   classes for all of these, so none of the callbacks could ever have fired.

2. `com.android.billingclient:billing` was never listed in buildozer.spec's
   `android.gradle_dependencies` at all, so every `autoclass("com.android.
   billingclient...")` call below would have failed with a ClassNotFoundException
   the moment it ran (caught here, so it fails quiet rather than crashing --
   but real purchases could never have worked). Fixed alongside this file.

This targets Billing Library 6.x's ProductDetails-based API (the SkuDetails-
based API this file previously used was deprecated by Google in 2022 and
Play Console has since required migrating off it). A specific version is
pinned in buildozer.spec; if that's bumped to a newer major version later,
re-check this file's method names against that version's release notes --
Google has changed this API's shape more than once (e.g. v7 wraps
onProductDetailsResponse's second argument in a QueryProductDetailsResult
instead of passing the List directly).

IMPORTANT: none of the Android-specific code paths in this file can be
exercised outside a real device signed against a Play Console app with the
subscription products below actually configured (license testing track) --
there is no emulator/CI coverage for this. Treat this as carefully-reasoned
best-effort against the documented API, not as verified-working, until it's
been through an actual on-device purchase using Play's license testers.
"""

import logging
from datetime import date, timedelta

from kivy.utils import platform

log = logging.getLogger(__name__)

PRODUCT_ID_MONTHLY = "solarquote_pro_monthly"
PRODUCT_ID_YEARLY = "solarquote_pro_yearly"

TRIAL_DAYS = 7

_SUBSCRIPTION_PRODUCTS = [PRODUCT_ID_MONTHLY, PRODUCT_ID_YEARLY]

_RESPONSE_OK = 0  # BillingClient.BillingResponseCode.OK
_PURCHASED = 1  # Purchase.PurchaseState.PURCHASED (NOT 0 -- 0 is UNSPECIFIED_STATE;
# a previous version of this file checked for 0, which meant a genuinely
# purchased subscription could never actually register as active)


class BillingManager:
    """Manages Google Play Billing for SolarQuote Pro subscriptions."""

    def __init__(self):
        self._billing_client = None
        self._activity = None
        self._is_pro = False
        self._initialized = False
        self._connected = False
        # ProductDetails + chosen subscription offer token, keyed by product
        # id, populated once queryProductDetailsAsync succeeds. Needed to
        # actually launch a purchase, and to show real store-configured
        # prices instead of the hardcoded fallback strings.
        self._product_details = {}
        # Every PythonJavaClass listener instance must be kept alive by a
        # Python reference for as long as Java might call back into it --
        # pyjnius doesn't pin them, so an unreferenced listener can be
        # garbage-collected while Play Billing still expects to call it,
        # silently dropping the callback. Stored here rather than as local
        # variables in the methods that create them.
        self._listeners = {}
        # Optional callback the app can set (see main.py): called with no
        # args whenever a confirmed Play purchase changes the tier, so
        # always-visible UI (the persistent plan label) can refresh itself
        # without the user having to navigate somewhere that happens to
        # re-read the tier on its own. May fire from a non-Kivy thread --
        # this class does not assume anything about which thread calls it,
        # so the callback itself is responsible for getting back onto
        # Kivy's main thread before touching any widget.
        self.on_tier_changed = None

    # ------------------------------------------------------------------
    # Classloader fix
    # ------------------------------------------------------------------

    def _ensure_classloader(self) -> None:
        """Point the CURRENT thread's context classloader at the Activity's
        own classloader, which can see this app's bundled third-party
        classes (like anything under com.android.billingclient.api.*) --
        confirmed via `adb logcat` to be necessary, not a defensive guess:
        constructing a PythonJavaClass for PurchasesUpdatedListener threw
        "java.lang.IllegalArgumentException: interface
        com.android.billingclient.api.PurchasesUpdatedListener is not
        visible from class loader" without this. Root cause: a thread that
        attaches to the JVM (which is what happens under pyjnius) gets the
        bootstrap classloader by default, which only knows core
        java.*/android.* framework classes.

        Called at the top of every method that constructs a
        PythonJavaClass, not just once at startup: Play Billing's own
        callbacks (onBillingSetupFinished, onPurchasesUpdated, etc.) can
        land on a different thread than the one that ran _init_android(),
        most likely Android's actual UI thread rather than Kivy's own app
        thread -- and that thread would hit the exact same error
        independently the first time IT tries to construct a listener, if
        this hadn't already been set for it. Cheap and idempotent, so
        calling it defensively everywhere costs nothing.
        """
        try:
            from jnius import autoclass
            Thread = autoclass("java.lang.Thread")
            Thread.currentThread().setContextClassLoader(self._activity.getClassLoader())
        except Exception as exc:
            log.warning("Could not set context classloader: %s", exc)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize the billing client. Call once at app startup."""
        if self._initialized:
            return
        self._initialized = True

        if platform != "android":
            self._load_cached_tier()
            return

        try:
            self._init_android()
        except Exception:
            # _init_android() logs exactly which construction step failed
            # before re-raising -- this outer catch is only the final,
            # generic fallback so a broken billing setup degrades to cached
            # tier instead of crashing the app.
            log.exception("Billing init failed")
            self._load_cached_tier()

    def _init_android(self) -> None:
        # Every step below is its own try/except so a failure log names the
        # exact stage instead of a single "something in _init_android broke"
        # message with no way to tell which of six calls actually threw --
        # this is otherwise impossible to debug without a full logcat
        # session, and even then buried in noise.
        def _stage(name, fn):
            try:
                return fn()
            except Exception:
                log.exception("Billing init failed at stage: %s", name)
                raise

        from jnius import autoclass

        PythonActivity = _stage("autoclass(PythonActivity)",
                                 lambda: autoclass("org.kivy.android.PythonActivity"))
        self._activity = _stage("PythonActivity.mActivity", lambda: PythonActivity.mActivity)

        # See _ensure_classloader()'s docstring -- confirmed via `adb
        # logcat` this is required before constructing any listener below,
        # not a defensive guess.
        _stage("_ensure_classloader", self._ensure_classloader)

        BillingClient = _stage(
            "autoclass(BillingClient)",
            lambda: autoclass("com.android.billingclient.api.BillingClient"),
        )
        PendingPurchasesParams = _stage(
            "autoclass(PendingPurchasesParams)",
            lambda: autoclass("com.android.billingclient.api.PendingPurchasesParams"),
        )

        # PurchasesUpdatedListener is set once, at build time -- it's how
        # Play reports the result of every launchBillingFlow() call, not
        # something queried per-purchase like the other listeners below.
        self._listeners["purchases_updated"] = _stage(
            "construct PurchasesUpdatedListener", lambda: _PurchasesUpdatedListener(self),
        )

        builder = _stage("BillingClient.newBuilder", lambda: BillingClient.newBuilder(self._activity))
        builder = _stage(
            "builder.setListener", lambda: builder.setListener(self._listeners["purchases_updated"]),
        )
        # enablePendingPurchases() is documented as optional (only
        # setListener() is required for build() to succeed) but every
        # subscription this app sells needs it to actually be purchasable,
        # so it's still called unconditionally here -- not a mandatory
        # build() precondition, just a real functional requirement.
        # enableOneTimeProducts() -- matches Google's own official
        # subscriptions sample (play-billing-samples/subscriptions)
        # verbatim, even though this app sells no one-time products: an
        # empty PendingPurchasesParams isn't a documented, confirmed-valid
        # config, and the sample calls this unconditionally, so matching it
        # exactly removes the guesswork rather than trusting an assumption
        # that empty params would also work.
        pending_params = _stage(
            "PendingPurchasesParams.newBuilder().enableOneTimeProducts().build()",
            lambda: PendingPurchasesParams.newBuilder().enableOneTimeProducts().build(),
        )
        builder = _stage("builder.enablePendingPurchases", lambda: builder.enablePendingPurchases(pending_params))
        # Also from the official sample, and directly relevant to the
        # "not_connected" failures this is fixing: opts into the Billing
        # Library automatically reconnecting to the Play Store service if
        # the connection drops, instead of silently staying disconnected
        # until something explicitly calls startConnection() again.
        builder = _stage("builder.enableAutoServiceReconnection", builder.enableAutoServiceReconnection)
        self._billing_client = _stage("builder.build", builder.build)

        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._ensure_classloader()
        self._listeners["connect"] = _ConnectListener(self)
        self._billing_client.startConnection(self._listeners["connect"])
        # startConnection() doesn't raise on its own if the connection
        # attempt just never completes -- onBillingSetupFinished/
        # onBillingServiceDisconnected simply never fire, with nothing to
        # except. That's indistinguishable from "still connecting" without
        # a timeout, so this fires once, diagnostically, if a purchase gets
        # attempted well after startConnection() with no callback ever
        # having landed -- it doesn't retry or change behavior on its own.
        import threading

        def _check_stalled():
            if not self._connected:
                log.warning(
                    "Billing startConnection() called but no "
                    "onBillingSetupFinished/onBillingServiceDisconnected callback "
                    "has fired after 10s -- either the PurchasesUpdatedListener/"
                    "ConnectListener PythonJavaClass proxies aren't being "
                    "recognized as valid Java interface implementations, or Play "
                    "Store/Play Services isn't responding on this device."
                )

        threading.Timer(10.0, _check_stalled).start()

    def _on_connected(self) -> None:
        self._connected = True
        self._query_purchases()
        self._query_product_details()

    def _on_disconnected(self) -> None:
        self._connected = False

    # ------------------------------------------------------------------
    # Purchase query (entitlement check -- runs on every connect, i.e.
    # every cold start)
    # ------------------------------------------------------------------

    def _query_purchases(self) -> None:
        """Query active subscriptions from Google Play."""
        if not self._connected or not self._billing_client:
            self._load_cached_tier()
            return

        try:
            self._ensure_classloader()
            from jnius import autoclass

            QueryPurchasesParams = autoclass(
                "com.android.billingclient.api.QueryPurchasesParams"
            )
            BillingClient = autoclass("com.android.billingclient.api.BillingClient")

            params = (QueryPurchasesParams.newBuilder()
                      .setProductType(BillingClient.ProductType.SUBS)
                      .build())
            self._listeners["query_purchases"] = _PurchasesResponseListener(
                self, self._on_purchases_queried
            )
            self._billing_client.queryPurchasesAsync(params, self._listeners["query_purchases"])
        except Exception as exc:
            log.warning("queryPurchasesAsync failed: %s", exc)
            self._load_cached_tier()

    def _on_purchases_queried(self, billing_result, purchases_list) -> None:
        if billing_result.getResponseCode() != _RESPONSE_OK:
            log.warning("Query purchases failed: %s", billing_result.getDebugMessage())
            self._load_cached_tier()
            return
        self._process_purchases(purchases_list)

    def _process_purchases(self, purchases_list) -> None:
        """Process the list of purchases returned by Google Play.

        Only ever used to *confirm* a real subscription, never to deny one:
        Google Play has no record of a locally-tracked free trial (it isn't a
        Play-billed product), so treating "no purchases found" as "downgrade
        to Free" would kill an active trial the moment the app restarts on
        Android, since this runs on every cold start. When no purchase is
        found, defer entirely to database.get_tier(), which already knows how
        to evaluate a still-running trial on its own.
        """
        from db import database

        active_purchase = None
        if purchases_list is not None:
            try:
                for i in range(purchases_list.size()):
                    purchase = purchases_list.get(i)
                    if purchase.getPurchaseState() != _PURCHASED:
                        continue
                    products = purchase.getProducts()  # List<String>; getSkus() is the old v4 name
                    product_ids = [products.get(j) for j in range(products.size())]
                    if any(pid in _SUBSCRIPTION_PRODUCTS for pid in product_ids):
                        active_purchase = purchase
                        break
            except Exception as exc:
                log.warning("Error processing purchases: %s", exc)
                self._load_cached_tier()
                return

        if active_purchase is not None:
            # A confirmed real purchase always wins over -- and clears -- any
            # leftover trial state, so a subscriber is never later downgraded
            # by an old trial_end date (see database.get_tier()).
            was_pro = self._is_pro
            self._is_pro = True
            database.set_pro_source("purchase")
            database.set_trial_end(None)
            self._save_tier_to_db(True)
            if not active_purchase.isAcknowledged():
                self._acknowledge(active_purchase)
            if not was_pro and self.on_tier_changed:
                try:
                    self.on_tier_changed()
                except Exception as exc:
                    log.warning("on_tier_changed callback failed: %s", exc)
        else:
            self._load_cached_tier()

    # ------------------------------------------------------------------
    # Acknowledgement -- Google auto-refunds any subscription purchase not
    # acknowledged within 3 days, so this has to happen for every purchase,
    # not just ones made in the current app session.
    # ------------------------------------------------------------------

    def _acknowledge(self, purchase) -> None:
        try:
            self._ensure_classloader()
            from jnius import autoclass

            AcknowledgePurchaseParams = autoclass(
                "com.android.billingclient.api.AcknowledgePurchaseParams"
            )
            params = (AcknowledgePurchaseParams.newBuilder()
                      .setPurchaseToken(purchase.getPurchaseToken())
                      .build())
            listener = _AcknowledgeListener()
            self._listeners[f"ack_{purchase.getPurchaseToken()}"] = listener
            self._billing_client.acknowledgePurchase(params, listener)
        except Exception as exc:
            log.warning("acknowledgePurchase failed: %s", exc)

    # ------------------------------------------------------------------
    # Product details (prices + the offer token a purchase needs)
    # ------------------------------------------------------------------

    def _query_product_details(self) -> None:
        if not self._connected or not self._billing_client:
            return
        try:
            self._ensure_classloader()
            from jnius import autoclass

            BillingClient = autoclass("com.android.billingclient.api.BillingClient")
            QueryProductDetailsParams = autoclass(
                "com.android.billingclient.api.QueryProductDetailsParams"
            )
            Product = autoclass(
                "com.android.billingclient.api.QueryProductDetailsParams$Product"
            )
            ArrayList = autoclass("java.util.ArrayList")

            product_list = ArrayList()
            for product_id in _SUBSCRIPTION_PRODUCTS:
                product_list.add(
                    Product.newBuilder()
                    .setProductId(product_id)
                    .setProductType(BillingClient.ProductType.SUBS)
                    .build()
                )

            params = (QueryProductDetailsParams.newBuilder()
                      .setProductList(product_list)
                      .build())
            self._listeners["product_details"] = _ProductDetailsResponseListener(
                self, self._on_product_details
            )
            self._billing_client.queryProductDetailsAsync(params, self._listeners["product_details"])
        except Exception as exc:
            log.warning("queryProductDetailsAsync failed: %s", exc)

    def _on_product_details(self, billing_result, query_result) -> None:
        if billing_result.getResponseCode() != _RESPONSE_OK or query_result is None:
            log.warning("Product details fetch failed: %s", billing_result.getDebugMessage())
            return
        try:
            # query_result is a QueryProductDetailsResult (Billing Library
            # 8.0+), not the plain List<ProductDetails> older versions
            # passed directly -- unwrap it. Any product listed in
            # getUnfetchedProductList() (e.g. a product ID with no active
            # base plan in Play Console) simply won't appear in
            # self._product_details afterward, which launch_purchase()
            # already treats as "not ready yet" -- no separate handling
            # needed for the unfetched list itself.
            product_details_list = query_result.getProductDetailsList()
            for i in range(product_details_list.size()):
                details = product_details_list.get(i)
                offers = details.getSubscriptionOfferDetails()
                if offers is None or offers.size() == 0:
                    continue
                # A base plan can have multiple pricing phases (e.g. a
                # store-configured intro/trial phase followed by the ongoing
                # price) -- the LAST phase is the recurring price, which is
                # what should be shown/relied on, not whatever the first
                # (possibly discounted or free) phase happens to be.
                offer = offers.get(0)
                phases = offer.getPricingPhases().getPricingPhaseList()
                last_phase = phases.get(phases.size() - 1)
                self._product_details[details.getProductId()] = {
                    "details": details,
                    "offer_token": offer.getOfferToken(),
                    "formatted_price": last_phase.getFormattedPrice(),
                }
        except Exception as exc:
            log.warning("Error reading product details: %s", exc)

    # ------------------------------------------------------------------
    # Purchase flow
    # ------------------------------------------------------------------

    def launch_purchase(self, product_id: str) -> str:
        """Launch Google Play purchase flow for the given product.

        Returns "" on success (Play's own purchase sheet takes over from
        here -- the actual grant happens later, asynchronously, via
        _on_purchases_updated). Returns a short reason code on failure so
        the caller can tell the user *why* nothing happened instead of the
        button just silently doing nothing, which every one of these early
        returns used to do.
        """
        if platform != "android":
            return "not_android"

        if not self._connected or not self._billing_client or not self._activity:
            log.warning("Billing not connected, cannot launch purchase")
            return "not_connected"

        cached = self._product_details.get(product_id)
        if not cached:
            log.warning("No product details cached yet for %s -- retrying fetch", product_id)
            self._query_product_details()
            return "product_not_ready"

        try:
            from jnius import autoclass

            BillingFlowParams = autoclass("com.android.billingclient.api.BillingFlowParams")
            ProductDetailsParams = autoclass(
                "com.android.billingclient.api.BillingFlowParams$ProductDetailsParams"
            )
            ArrayList = autoclass("java.util.ArrayList")

            product_params = (ProductDetailsParams.newBuilder()
                               .setProductDetails(cached["details"])
                               .setOfferToken(cached["offer_token"])
                               .build())
            params_list = ArrayList()
            params_list.add(product_params)

            flow_params = (BillingFlowParams.newBuilder()
                           .setProductDetailsParamsList(params_list)
                           .build())
            self._billing_client.launchBillingFlow(self._activity, flow_params)
            return ""
        except Exception as exc:
            log.warning("launchBillingFlow failed: %s", exc)
            return "launch_failed"

    def _on_purchases_updated(self, billing_result, purchases_list) -> None:
        """Callback for the flow started by launch_purchase() -- Play reports
        the result (success, user cancelled, already owned, etc.) here."""
        if billing_result.getResponseCode() != _RESPONSE_OK:
            log.info("Purchase flow ended: %s", billing_result.getDebugMessage())
            return
        self._process_purchases(purchases_list)

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_purchases(self) -> bool:
        """Re-query Google Play for active subscriptions. Returns True if Pro."""
        if platform != "android":
            self._load_cached_tier()
            return self._is_pro

        if self._connected and self._billing_client:
            try:
                self._query_purchases()
                return self._is_pro
            except Exception as exc:
                log.warning("restore_purchases failed: %s", exc)

        self._load_cached_tier()
        return self._is_pro

    # ------------------------------------------------------------------
    # Tier helpers
    # ------------------------------------------------------------------

    def is_pro(self) -> bool:
        return self._is_pro

    def set_pro(self, value: bool) -> None:
        self._is_pro = value
        self._save_tier_to_db(value)

    def start_trial(self) -> None:
        from db import database
        end = database.get_trusted_today() + timedelta(days=TRIAL_DAYS)
        database.set_trial_end(end.isoformat())
        database.set_pro_source("trial")
        self.set_pro(True)

    def has_active_trial(self) -> bool:
        try:
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                return database.get_trusted_today() <= date.fromisoformat(trial_end)
        except (TypeError, ValueError):
            pass
        return False

    def get_trial_days_left(self) -> int:
        try:
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                return max(0, (date.fromisoformat(trial_end) - database.get_trusted_today()).days)
        except (TypeError, ValueError):
            pass
        return 0

    # ------------------------------------------------------------------
    # Local cache
    # ------------------------------------------------------------------

    def _load_cached_tier(self) -> None:
        try:
            from db import database
            self._is_pro = database.get_tier() == "pro"
        except Exception:
            self._is_pro = False

    def _save_tier_to_db(self, is_pro: bool) -> None:
        try:
            from db import database
            database.set_tier("pro" if is_pro else "free")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Price strings
    # ------------------------------------------------------------------

    def get_monthly_price(self) -> str:
        cached = self._product_details.get(PRODUCT_ID_MONTHLY)
        return cached["formatted_price"] if cached else "P299/month"

    def get_yearly_price(self) -> str:
        cached = self._product_details.get(PRODUCT_ID_YEARLY)
        return cached["formatted_price"] if cached else "P2,990/year"

    def get_yearly_savings(self) -> str:
        return "Save 17%"


# ----------------------------------------------------------------------
# PythonJavaClass listener implementations.
#
# Each of these bridges a Google Play Billing Java interface to Python.
# jnius requires this exact pattern -- __javainterfaces__ naming the
# interface (JNI slash-separated form) and @java_method declaring each
# method's JNI signature -- a plain Python class with matching method names
# does NOT implement a Java interface as far as the JVM/JNI boundary is
# concerned.
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

        def __init__(self, manager):
            super().__init__()
            self._manager = manager

        @java_method(_billing_result_sig())
        def onBillingSetupFinished(self, billing_result):
            if billing_result.getResponseCode() == _RESPONSE_OK:
                self._manager._on_connected()
            else:
                log.warning("Billing setup failed: %s", billing_result.getDebugMessage())
                self._manager._load_cached_tier()

        @java_method("()V")
        def onBillingServiceDisconnected(self):
            self._manager._on_disconnected()

    class PurchasesUpdatedListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/PurchasesUpdatedListener"]

        def __init__(self, manager):
            super().__init__()
            self._manager = manager

        @java_method(_billing_result_sig("Ljava/util/List;"))
        def onPurchasesUpdated(self, billing_result, purchases_list):
            self._manager._on_purchases_updated(billing_result, purchases_list)

    class PurchasesResponseListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/PurchasesResponseListener"]

        def __init__(self, manager, callback):
            super().__init__()
            self._manager = manager
            self._callback = callback

        @java_method(_billing_result_sig("Ljava/util/List;"))
        def onQueryPurchasesResponse(self, billing_result, purchases_list):
            self._callback(billing_result, purchases_list)

    class ProductDetailsResponseListener(PythonJavaClass):
        __javainterfaces__ = ["com/android/billingclient/api/ProductDetailsResponseListener"]

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

        @java_method(_billing_result_sig())
        def onAcknowledgePurchaseResponse(self, billing_result):
            if billing_result.getResponseCode() != _RESPONSE_OK:
                log.warning("acknowledgePurchase failed: %s", billing_result.getDebugMessage())

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


def _AcknowledgeListener():  # noqa: N802
    return _get_java_classes()["acknowledge"]()
