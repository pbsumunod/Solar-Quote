"""Dependency-free verification of narrowly scoped RSA signed entitlements."""

import base64
import hashlib
import hmac
import json

_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def verify_entitlement(token, *, modulus_hex, exponent, audience,
                       purchase_token, now, max_lifetime, nonce=None, fresh_response=False):
    """Verify the fixed RSA PKCS#1 v1.5 SHA-256 signature and scoped claims."""
    if not isinstance(token, str) or len(token) > 16384:
        raise ValueError("Invalid entitlement")
    payload_encoded, signature_encoded = token.split(".")
    payload = _decode(payload_encoded)
    signature = _decode(signature_encoded)
    modulus = int(modulus_hex, 16)
    if modulus.bit_length() < 2048 or exponent != 65537:
        raise ValueError("Invalid verification key")
    size = (modulus.bit_length() + 7) // 8
    if len(signature) != size or int.from_bytes(signature, "big") >= modulus:
        raise ValueError("Invalid signature")
    decoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(size, "big")
    digest = _SHA256_DIGEST_INFO + hashlib.sha256(payload).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    if not hmac.compare_digest(decoded, expected):
        raise ValueError("Invalid signature")
    claims = json.loads(payload)
    if not isinstance(claims, dict) or claims.get("aud") != audience:
        raise ValueError("Wrong entitlement audience")
    expected_hash = hashlib.sha256(purchase_token.encode()).hexdigest()
    if not hmac.compare_digest(str(claims.get("purchase_token_hash", "")), expected_hash):
        raise ValueError("Wrong purchase token")
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("Wrong response nonce")
    issued, expires = claims.get("iat"), claims.get("exp")
    # The pinned signature and a fresh unpredictable nonce authenticate server
    # time independently of a misconfigured device clock.
    comparison_time = issued if fresh_response and nonce is not None else now
    if (type(issued) is not int or type(expires) is not int
            or type(claims.get("active")) is not bool
            or issued < 0 or issued > comparison_time + 300 or expires <= comparison_time
            or expires <= issued or expires - issued > max_lifetime):
        raise ValueError("Expired or invalid entitlement lifetime")
    return claims
