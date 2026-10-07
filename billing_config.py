"""Public settings for the optional purchase-verification service.

Leave BACKEND_URL empty for client-only Play verification. Configure its HTTPS
URL and the RSA public modulus printed by backend/generate_key.py to enable it.
Never put service credentials or the private signing key in this module.
"""

BACKEND_URL = ""
PUBLIC_KEY_MODULUS_HEX = ""
PUBLIC_KEY_EXPONENT = 65537
PACKAGE_NAME = "org.solarclientfinder.solarclientfinder"
OFFLINE_GRACE_SECONDS = 7 * 24 * 60 * 60
