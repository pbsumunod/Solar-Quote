"""Google Play Billing integration for SolarQuote Pro subscriptions.

Uses the Google Play Billing Library via jnius to query and purchase
subscriptions. On Android, subscriptions are tied to the Google account
used at purchase time — no in-app login is needed. On reinstall,
queryPurchasesAsync() restores the active subscription from Google Play.

Falls back gracefully on non-Android platforms or when billing is unavailable.
"""

import json
import logging
from datetime import date, timedelta

from kivy.utils import platform

log = logging.getLogger(__name__)

PRODUCT_ID_MONTHLY = "solarquote_pro_monthly"
PRODUCT_ID_YEARLY = "solarquote_pro_yearly"

TRIAL_DAYS = 7

_INAPP_PRODUCTS = [PRODUCT_ID_MONTHLY, PRODUCT_ID_YEARLY]


class BillingManager:
    """Manages Google Play Billing for SolarQuote Pro subscriptions."""

    def __init__(self):
        self._billing_client = None
        self._is_pro = False
        self._initialized = False
        self._connected = False

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
        except Exception as exc:
            log.warning("Billing init failed: %s", exc)
            self._load_cached_tier()

    def _init_android(self) -> None:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        self._activity = PythonActivity.mActivity

        BillingClient = autoclass("com.android.billingclient.api.BillingClient")
        Purchase = autoclass("com.android.billingclient.api.Purchase")
        SkuDetailsParams = autoclass(
            "com.android.billingclient.api.SkuDetailsParams"
        )

        self._BillingClient = BillingClient
        self._Purchase = Purchase
        self._SkuDetailsParams = SkuDetailsParams

        # Build the billing client
        builder = BillingClient.newBuilder(self._activity)
        self._billing_client = builder.enablePendingPurchases().build()

        # Attempt to connect and query purchases
        self._connect_and_query()

    # ------------------------------------------------------------------
    # Connection & purchase query
    # ------------------------------------------------------------------

    def _connect_and_query(self) -> None:
        """Start connection to Google Play and query purchases once ready."""
        from jnius import autoclass

        BillingClientStateListener = autoclass(
            "com.android.billingclient.api.BillingClientStateListener"
        )
        PurchasesResponseListener = autoclass(
            "com.android.billingclient.api.PurchasesResponseListener"
        )

        manager = self

        class _ConnectListener:
            def onBillingSetupFinished(self, billingResult):
                if billingResult.getResponseCode() == 0:  # OK
                    manager._connected = True
                    manager._query_purchases()
                else:
                    log.warning("Billing setup failed: %s", billingResult.getDebugMessage())
                    manager._load_cached_tier()

            def onBillingServiceDisconnected(self):
                manager._connected = False

        class _QueryListener:
            def onQueryPurchasesResponse(self, billingResult, purchasesList):
                if billingResult.getResponseCode() == 0:
                    manager._process_purchases(purchasesList)
                else:
                    log.warning("Query purchases failed: %s", billingResult.getDebugMessage())
                    manager._load_cached_tier()

        self._billing_client.startConnection(_ConnectListener())
        self._purchases_listener = _QueryListener()

    def _query_purchases(self) -> None:
        """Query active subscriptions from Google Play."""
        if not self._connected or not self._billing_client:
            self._load_cached_tier()
            return

        try:
            # queryPurchasesAsync requires BillingFlowParams.newBuilder which
            # needs the product type string. Use 0 for SUBS (enum ordinal).
            self._billing_client.queryPurchasesAsync(
                "subs", self._purchases_listener
            )
        except Exception as exc:
            log.warning("queryPurchasesAsync failed: %s", exc)
            self._load_cached_tier()

    def _process_purchases(self, purchasesList) -> None:
        """Process the list of purchases returned by Google Play."""
        if purchasesList is None:
            self._load_cached_tier()
            return

        active = False
        try:
            for i in range(purchasesList.size()):
                purchase = purchasesList.get(i)
                # ACKNOWLEDGED == 1, purchaseState == 0 (purchased)
                if (purchase.getPurchaseState() == 0
                        and purchase.isAcknowledged()):
                    sku = purchase.getSkus().get(0) if purchase.getSkus().size() > 0 else ""
                    if sku in _INAPP_PRODUCTS:
                        active = True
                        break
        except Exception as exc:
            log.warning("Error processing purchases: %s", exc)

        self._is_pro = active
        self._save_tier_to_db(active)

    # ------------------------------------------------------------------
    # Purchase flow
    # ------------------------------------------------------------------

    def launch_purchase(self, product_id: str) -> None:
        """Launch Google Play purchase flow for the given product."""
        if platform != "android":
            return

        if not self._connected or not self._billing_client:
            log.warning("Billing not connected, cannot launch purchase")
            return

        try:
            from jnius import autoclass

            SkuDetailsParams = autoclass(
                "com.android.billingclient.api.SkuDetailsParams"
            )
            BillingFlowParams = autoclass(
                "com.android.billingclient.api.BillingFlowParams"
            )

            class _SkuListener:
                def __init__(self, mgr):
                    self.mgr = mgr
                def onSkuDetailsResponse(self, billingResult, skuDetailsList):
                    if billingResult.getResponseCode() != 0 or skuDetailsList is None or skuDetailsList.size() == 0:
                        log.warning("SkuDetails fetch failed")
                        return
                    try:
                        details = skuDetailsList.get(0)
                        params = (BillingFlowParams.newBuilder()
                                  .setSkuDetails(details)
                                  .build())
                        self.mgr._billing_client.launchBillingFlow(
                            self.mgr._activity, params
                        )
                    except Exception as exc:
                        log.warning("launchBillingFlow failed: %s", exc)

            sku_params = (SkuDetailsParams.newBuilder()
                          .setSkusList([product_id])
                          .setType("subs")
                          .build())
            self._billing_client.querySkuDetailsAsync(sku_params, _SkuListener(self))
        except Exception as exc:
            log.warning("launch_purchase failed: %s", exc)

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
        import internet_time
        from db import database
        end = internet_time.today() + timedelta(days=TRIAL_DAYS)
        database.set_trial_end(end.isoformat())
        self.set_pro(True)

    def has_active_trial(self) -> bool:
        try:
            import internet_time
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                return internet_time.today() <= date.fromisoformat(trial_end)
        except (TypeError, ValueError):
            pass
        return False

    def get_trial_days_left(self) -> int:
        try:
            import internet_time
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                return max(0, (date.fromisoformat(trial_end) - internet_time.today()).days)
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
        return "P299/month"

    def get_yearly_price(self) -> str:
        return "P2,990/year"

    def get_yearly_savings(self) -> str:
        return "Save 17%"
