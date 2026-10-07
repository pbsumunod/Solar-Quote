"""Google Play verification and signed, token-bound cached entitlements."""

import base64
import hashlib
import json
import time
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

PRODUCTS = {"solarquote_pro_monthly", "solarquote_pro_yearly"}
ACTIVE_STATES = {"SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
                 "SUBSCRIPTION_STATE_CANCELED"}
KNOWN_STATES = ACTIVE_STATES | {
    "SUBSCRIPTION_STATE_UNSPECIFIED", "SUBSCRIPTION_STATE_PENDING",
    "SUBSCRIPTION_STATE_PAUSED", "SUBSCRIPTION_STATE_ON_HOLD",
    "SUBSCRIPTION_STATE_EXPIRED", "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED",
}
ACKNOWLEDGEMENT_STATES = {
    "ACKNOWLEDGEMENT_STATE_UNSPECIFIED", "ACKNOWLEDGEMENT_STATE_PENDING",
    "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
}


def encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class BillingService:
    def __init__(self, private_key, fetch_subscription, acknowledge,
                 package="org.solarclientfinder.solarclientfinder", grace_seconds=604800,
                 clock=time.time):
        self.private_key = private_key
        self.fetch_subscription = fetch_subscription
        self.acknowledge = acknowledge
        self.package = package
        self.grace_seconds = grace_seconds
        self.clock = clock

    def verify(self, purchase_token, nonce):
        subscription = self.fetch_subscription(purchase_token)
        # Malformed upstream data must remain a retryable service error. An
        # inactive signed response would incorrectly revoke a valid app cache.
        if not isinstance(subscription, dict):
            raise RuntimeError("Invalid Google subscription response")
        state = subscription.get("subscriptionState")
        acknowledgement = subscription.get("acknowledgementState")
        items = subscription.get("lineItems")
        if (not isinstance(state, str) or state not in KNOWN_STATES
                or not isinstance(items, list)
                or any(not isinstance(item, dict) for item in items)
                or not isinstance(acknowledgement, str)
                or acknowledgement not in ACKNOWLEDGEMENT_STATES):
            raise RuntimeError("Invalid Google subscription response")
        now = int(self.clock())
        valid_items = []
        for item in items:
            product = item.get("productId")
            if not isinstance(product, str) or not product:
                raise RuntimeError("Invalid Google line item response")
            if product not in PRODUCTS:
                continue
            # Pending purchases do not yet have a granted/expiring entitlement.
            if item.get("expiryTime") is None and state in {
                    "SUBSCRIPTION_STATE_PENDING", "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED"}:
                continue
            try:
                if not isinstance(item.get("expiryTime"), str):
                    raise ValueError("Missing expiry")
                expiry = datetime.fromisoformat(item["expiryTime"].replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    raise ValueError("Missing expiry timezone")
                valid_items.append((int(expiry.timestamp()), product))
            except (KeyError, ValueError, TypeError, OverflowError, OSError) as exc:
                raise RuntimeError("Invalid Google line item expiry") from exc
        expiry = max((item[0] for item in valid_items), default=0)
        active = state in ACTIVE_STATES and expiry > now
        if active:
            if acknowledgement == "ACKNOWLEDGEMENT_STATE_PENDING":
                product = max(valid_items)[1]
                self.acknowledge(product, purchase_token)
            elif acknowledgement != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED":
                # A malformed upstream response is retryable. Do not sign a
                # grant without acknowledgement, or revoke a valid app cache.
                raise RuntimeError("Unrecognized Google acknowledgement state")
        claims = {"aud": self.package, "iat": now,
                  "exp": min(expiry, now + self.grace_seconds) if active else now + 60,
                  "active": active, "nonce": nonce,
                  "purchase_token_hash": hashlib.sha256(purchase_token.encode()).hexdigest()}
        payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        signature = self.private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        return encode(payload) + "." + encode(signature)
