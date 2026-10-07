import base64
import io
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.server import Application
from backend.service import BillingService
from billing_entitlements import verify_entitlement

NOW = 1800000000
TOKEN = "valid-purchase-token"
NONCE = "request_nonce_with_24_chars"
PACKAGE = "org.solarclientfinder.solarclientfinder"


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def service(private_key, state="SUBSCRIPTION_STATE_ACTIVE", remaining=3600):
    acknowledgements = []
    expiry = datetime.fromtimestamp(NOW + remaining, timezone.utc).isoformat()
    return BillingService(private_key, lambda _token: {
        "subscriptionState": state, "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "lineItems": [{"productId": "solarquote_pro_monthly", "expiryTime": expiry}]},
        lambda product, token: acknowledgements.append((product, token)), clock=lambda: NOW), acknowledgements


def verify(private_key, signed, **overrides):
    options = dict(modulus_hex=format(private_key.public_key().public_numbers().n, "x"),
                   exponent=65537, audience=PACKAGE, purchase_token=TOKEN,
                   now=NOW, max_lifetime=604800, nonce=NONCE)
    options.update(overrides)
    return verify_entitlement(signed, **options)


@pytest.mark.parametrize("state,active", [
    ("SUBSCRIPTION_STATE_ACTIVE", True),
    ("SUBSCRIPTION_STATE_CANCELED", True),
    ("SUBSCRIPTION_STATE_IN_GRACE_PERIOD", True),
    ("SUBSCRIPTION_STATE_ON_HOLD", False),
    ("SUBSCRIPTION_STATE_PAUSED", False),
    ("SUBSCRIPTION_STATE_EXPIRED", False),
    ("SUBSCRIPTION_STATE_PENDING", False),
    ("SUBSCRIPTION_STATE_UNSPECIFIED", False),
    ("SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED", False)])
def test_subscription_lifecycle_and_acknowledgement(private_key, state, active):
    backend, acknowledgements = service(private_key, state)
    claims = verify(private_key, backend.verify(TOKEN, NONCE))
    assert claims["active"] is active
    assert bool(acknowledgements) is active


def test_expired_cancelled_subscription_does_not_grant_access(private_key):
    backend, acknowledgements = service(private_key, "SUBSCRIPTION_STATE_CANCELED", remaining=-1)
    assert verify(private_key, backend.verify(TOKEN, NONCE))["active"] is False
    assert acknowledgements == []


@pytest.mark.parametrize("acknowledgement", [None, "ACKNOWLEDGEMENT_STATE_UNSPECIFIED", "unknown"])
def test_active_purchase_with_malformed_acknowledgement_is_retryable(private_key, acknowledgement):
    backend, acknowledgements = service(private_key)
    original = backend.fetch_subscription
    def malformed(token):
        subscription = original(token)
        if acknowledgement is None:
            subscription.pop("acknowledgementState")
        else:
            subscription["acknowledgementState"] = acknowledgement
        return subscription
    backend.fetch_subscription = malformed
    status, body = request(Application(backend), "/verify", {"purchase_token": TOKEN, "nonce": NONCE})
    assert status == "503 Service Unavailable"
    assert "entitlement" not in body
    assert acknowledgements == []


@pytest.mark.parametrize("malformed", [
    None, [], "unexpected payload",
    {"subscriptionState": None}, {"subscriptionState": []},
    {"subscriptionState": "unknown"}, {},
    {"lineItems": None}, {"lineItems": {}}, {"lineItems": "unexpected items"},
    {"lineItems": [None]}, {"lineItems": ["unexpected item"]},
    {"lineItems": [{}]}, {"lineItems": [{"productId": []}]},
])
def test_malformed_google_subscription_shape_is_retryable(private_key, malformed):
    backend, acknowledgements = service(private_key)
    original = backend.fetch_subscription(TOKEN)
    # A dict denotes a field override; other values replace the whole response.
    if isinstance(malformed, dict):
        response = dict(original, **malformed)
        if not malformed:
            response.pop("subscriptionState")
    else:
        response = malformed
    backend.fetch_subscription = lambda _token: response
    status, body = request(Application(backend), "/verify", {"purchase_token": TOKEN, "nonce": NONCE})
    assert status == "503 Service Unavailable"
    assert body == {"error": "verification_unavailable"}
    assert acknowledgements == []


@pytest.mark.parametrize("expiry", [None, 123, "invalid", "2027-01-01T00:00:00"])
def test_malformed_granted_expiry_is_retryable(private_key, expiry):
    backend, acknowledgements = service(private_key)
    subscription = backend.fetch_subscription(TOKEN)
    subscription["lineItems"][0]["expiryTime"] = expiry
    backend.fetch_subscription = lambda _token: subscription
    status, body = request(Application(backend), "/verify", {"purchase_token": TOKEN, "nonce": NONCE})
    assert status == "503 Service Unavailable"
    assert "entitlement" not in body
    assert acknowledgements == []


def test_pending_purchase_without_expiry_remains_signed_inactive(private_key):
    backend, acknowledgements = service(private_key, "SUBSCRIPTION_STATE_PENDING")
    subscription = backend.fetch_subscription(TOKEN)
    subscription["lineItems"][0].pop("expiryTime")
    subscription["acknowledgementState"] = "ACKNOWLEDGEMENT_STATE_UNSPECIFIED"
    backend.fetch_subscription = lambda _token: subscription
    assert verify(private_key, backend.verify(TOKEN, NONCE))["active"] is False
    assert acknowledgements == []


@pytest.mark.parametrize("overrides", [{"purchase_token": "another-token"},
    {"nonce": "other-request-nonce"}, {"audience": "other.package"}, {"now": NOW + 3600}])
def test_entitlement_is_bound_to_token_nonce_package_and_expiry(private_key, overrides):
    backend, _ = service(private_key)
    with pytest.raises(ValueError):
        verify(private_key, backend.verify(TOKEN, NONCE), **overrides)


def test_modified_payload_and_wrong_signer_are_rejected(private_key):
    backend, _ = service(private_key)
    signed = backend.verify(TOKEN, NONCE)
    payload, signature = signed.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["exp"] += 1
    modified = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + "." + signature
    with pytest.raises(ValueError):
        verify(private_key, modified)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError):
        verify(other, signed)


def test_fresh_signed_nonce_can_correct_a_bad_device_clock(private_key):
    backend, _ = service(private_key)
    signed = backend.verify(TOKEN, NONCE)
    assert verify(private_key, signed, now=NOW + 10 * 365 * 86400,
                  fresh_response=True)["active"] is True
    with pytest.raises(ValueError):
        verify(private_key, signed, now=NOW + 10 * 365 * 86400)


def request(app, path, data, authorization=""):
    payload = json.dumps(data).encode()
    environ = {"PATH_INFO": path, "REQUEST_METHOD": "POST", "CONTENT_LENGTH": str(len(payload)),
               "REMOTE_ADDR": "127.0.0.1", "HTTP_AUTHORIZATION": authorization,
               "wsgi.input": io.BytesIO(payload)}
    statuses = []
    body = b"".join(app(environ, lambda status, _headers: statuses.append(status)))
    return statuses[0], json.loads(body)


def test_local_verification_endpoint_returns_a_valid_signed_response(private_key):
    backend, _ = service(private_key)
    status, body = request(Application(backend), "/verify", {"purchase_token": TOKEN, "nonce": NONCE})
    assert status == "200 OK"
    assert verify(private_key, body["entitlement"])["active"] is True


def test_google_failure_is_retryable_without_exposing_sensitive_tokens(private_key):
    backend, _ = service(private_key)
    def unavailable(_token):
        raise RuntimeError("upstream URL contains " + TOKEN)
    backend.fetch_subscription = unavailable
    status, body = request(Application(backend), "/verify", {"purchase_token": TOKEN, "nonce": NONCE})
    assert status == "503 Service Unavailable"
    assert TOKEN not in json.dumps(body)


def test_notifications_require_verified_push_identity_and_correct_package(private_key):
    backend, _ = service(private_key)
    app = Application(backend, verify_push=lambda token: None)
    message = {"packageName": PACKAGE, "subscriptionNotification": {"purchaseToken": TOKEN}}
    data = {"message": {"data": base64.b64encode(json.dumps(message).encode()).decode()}}
    assert request(app, "/notifications", data)[0] == "401 Unauthorized"
    assert request(app, "/notifications", data, "Bearer verified-google-jwt")[0] == "200 OK"
    message["packageName"] = "other.package"
    data["message"]["data"] = base64.b64encode(json.dumps(message).encode()).decode()
    assert request(app, "/notifications", data, "Bearer verified-google-jwt")[0] == "400 Bad Request"
