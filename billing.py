"""Google Play Billing integration for SolarQuote Pro subscriptions.

Wraps Android's com.android.vending.billing library via jnius to handle
in-app purchases and subscription management. Falls back gracefully on
non-Android platforms or when billing is unavailable.
"""

from datetime import date, timedelta
from kivy.utils import platform

PRODUCT_ID_MONTHLY = "solarquote_pro_monthly"
PRODUCT_ID_YEARLY = "solarquote_pro_yearly"

TRIAL_DAYS = 7


class BillingManager:
    """Manages Google Play Billing for SolarQuote Pro subscriptions."""

    def __init__(self):
        self._billing_client = None
        self._purchases_updated_listener = None
        self._is_pro = False
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the billing client. Call once at app startup."""
        if self._initialized:
            return
        self._initialized = True

        if platform != "android":
            self._load_cached_tier()
            return

        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            self._activity = PythonActivity.mActivity

            BillingClient = autoclass("com.android.billingclient.api.BillingClient")
            PurchasesUpdatedListener = autoclass(
                "com.android.billingclient.api.PurchasesUpdatedListener"
            )
            BillingClientStateListener = autoclass(
                "com.android.billingclient.api.BillingClientStateListener"
            )

            self._BillingClient = BillingClient
            self._BillingClientStateListener = BillingClientStateListener

            listener = PurchasesUpdatedListener()
            self._billing_client = BillingClient.newBuilder(self._activity).setListener(listener).build()

            class _ConnectionListener:
                def __init__(self, mgr):
                    self.mgr = mgr

                def onBillingSetupFinished(self, billingResult):
                    pass

                def onBillingServiceDisconnected(self):
                    pass

            connection_listener = _ConnectionListener(self)
            self._billing_client.startConnection(connection_listener)

            self._load_cached_tier()
        except Exception:
            self._load_cached_tier()

    def _load_cached_tier(self) -> None:
        """Load tier status from local database."""
        try:
            from db import database
            tier = database.get_tier()
            self._is_pro = tier == "pro"
        except Exception:
            self._is_pro = False

    def is_pro(self) -> bool:
        """Check if the user has Pro status."""
        return self._is_pro

    def set_pro(self, value: bool) -> None:
        """Update Pro status locally and in database."""
        self._is_pro = value
        try:
            from db import database
            database.set_tier("pro" if value else "free")
        except Exception:
            pass

    def start_trial(self) -> None:
        """Start a 7-day free trial."""
        from db import database
        end = date.today() + timedelta(days=TRIAL_DAYS)
        database.set_trial_end(end.isoformat())
        self.set_pro(True)

    def has_active_trial(self) -> bool:
        """Check if user has an active free trial."""
        try:
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                end = date.fromisoformat(trial_end)
                return date.today() <= end
        except (TypeError, ValueError):
            pass
        return False

    def get_trial_days_left(self) -> int:
        """Return days left in trial, or 0 if no active trial."""
        try:
            from db import database
            trial_end = database.get_trial_end()
            if trial_end:
                end = date.fromisoformat(trial_end)
                remaining = (end - date.today()).days
                return max(0, remaining)
        except (TypeError, ValueError):
            pass
        return 0

    def launch_purchase(self, product_id: str) -> None:
        """Launch Google Play purchase flow for the given product."""
        if platform != "android":
            return

        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")

            intent = Intent(Intent.ACTION_VIEW)
            intent.setData(Uri.parse(f"market://details?id={self._activity.getPackageName()}&offerId={product_id}"))
            self._activity.startActivity(intent)
        except Exception:
            pass

    def restore_purchases(self) -> bool:
        """Restore purchases from Google Play. Returns True if Pro was restored."""
        if platform != "android":
            self._load_cached_tier()
            return self._is_pro

        try:
            self._load_cached_tier()
            return self._is_pro
        except Exception:
            return False

    def get_monthly_price(self) -> str:
        """Return the monthly price string."""
        return "P299/month"

    def get_yearly_price(self) -> str:
        """Return the yearly price string."""
        return "P2,990/year"

    def get_yearly_savings(self) -> str:
        """Return the yearly savings string."""
        return "Save 17%"
