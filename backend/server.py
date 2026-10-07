"""Local runnable WSGI service. Deploy behind TLS with a production WSGI server."""

import base64
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote
from wsgiref.simple_server import make_server

from cryptography.hazmat.primitives import serialization

from backend.service import BillingService

_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
_NONCE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def build_service():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    package = os.getenv("PLAY_PACKAGE_NAME", "org.solarclientfinder.solarclientfinder")
    key_path = os.environ["ENTITLEMENT_PRIVATE_KEY_PATH"]
    private_key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    if private_key.key_size < 2048:
        raise ValueError("Signing key must be RSA 2048 bits or larger")
    credentials, _project = google.auth.default(scopes=[_SCOPE])
    session = AuthorizedSession(credentials)
    base = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/" + quote(package, safe="")

    def fetch(token):
        response = session.get(base + "/purchases/subscriptionsv2/tokens/" + quote(token, safe=""), timeout=15)
        response.raise_for_status()
        return response.json()

    def acknowledge(product, token):
        response = session.post(base + "/purchases/subscriptions/" + quote(product, safe="")
                                + "/tokens/" + quote(token, safe="") + ":acknowledge", json={}, timeout=15)
        response.raise_for_status()

    return BillingService(private_key, fetch, acknowledge, package=package)


class Application:
    def __init__(self, service, verify_push=None):
        self.service = service
        self.verify_push = verify_push or self._verify_push
        self._requests = defaultdict(deque)
        self._lock = threading.Lock()

    def _verify_push(self, bearer):
        audience = os.getenv("RTDN_AUDIENCE")
        account = os.getenv("RTDN_SERVICE_ACCOUNT_EMAIL")
        if not audience or not account:
            raise PermissionError("RTDN is not configured")
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(bearer, Request(), audience=audience)
        if claims.get("email") != account or claims.get("email_verified") is not True:
            raise PermissionError("Unauthorized notification")

    def __call__(self, environ, start_response):
        status, body = "200 OK", {}
        try:
            path = environ.get("PATH_INFO")
            if path == "/health" and environ.get("REQUEST_METHOD") == "GET":
                body = {"status": "ok"}
            elif path in ("/verify", "/notifications") and environ.get("REQUEST_METHOD") == "POST":
                client = environ.get("REMOTE_ADDR", "unknown")
                now = time.monotonic()
                with self._lock:
                    entries = self._requests[client]
                    while entries and entries[0] < now - 60:
                        entries.popleft()
                    if len(entries) >= 30:
                        raise OverflowError("Rate limit")
                    entries.append(now)
                    # Bound memory for a public endpoint with many remote clients.
                    if len(self._requests) > 10000:
                        self._requests.clear()
                size = int(environ.get("CONTENT_LENGTH", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Invalid request size")
                if path == "/notifications":
                    authorization = environ.get("HTTP_AUTHORIZATION", "")
                    if not authorization.startswith("Bearer "):
                        raise PermissionError("Missing notification identity")
                    try:
                        self.verify_push(authorization[7:])
                    except Exception as exc:
                        raise PermissionError("Unauthorized notification") from exc
                data = json.loads(environ["wsgi.input"].read(size))
                if path == "/notifications":
                    message = json.loads(base64.b64decode(data["message"]["data"], validate=True))
                    if message.get("packageName") != self.service.package:
                        raise ValueError("Wrong package")
                    notification = message.get("subscriptionNotification")
                    if not notification:
                        # Pub/Sub test notifications require successful acknowledgement too.
                        body = {"accepted": True}
                    else:
                        self.service.verify(notification["purchaseToken"], "notification-verification")
                        body = {"accepted": True}
                else:
                    token, nonce = data["purchase_token"], data["nonce"]
                    if not isinstance(token, str) or not 8 <= len(token) <= 4096 or not _NONCE.fullmatch(nonce):
                        raise ValueError("Invalid verification request")
                    body = {"entitlement": self.service.verify(token, nonce)}
            else:
                status, body = "404 Not Found", {"error": "not_found"}
        except OverflowError:
            status, body = "429 Too Many Requests", {"error": "rate_limited"}
        except PermissionError:
            status, body = "401 Unauthorized", {"error": "unauthorized"}
        except (ValueError, KeyError, TypeError):
            status, body = "400 Bad Request", {"error": "invalid_request"}
        except Exception:
            # Purchase tokens appear in Google URL paths; never echo exceptions or request bodies.
            status, body = "503 Service Unavailable", {"error": "verification_unavailable"}
        payload = json.dumps(body).encode()
        start_response(status, [("Content-Type", "application/json"), ("Cache-Control", "no-store"),
                                ("Content-Length", str(len(payload)))])
        return [payload]


def create_app():
    return Application(build_service())


if __name__ == "__main__":
    with make_server("127.0.0.1", int(os.getenv("PORT", "8080")), create_app()) as server:
        server.serve_forever()
