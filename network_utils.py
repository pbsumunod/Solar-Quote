"""Portable certificate validation for urllib on packaged Android Python."""

import ssl
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def tls_context():
    # Android's CA store is not OpenSSL's configured desktop CA directory.
    # Ship the maintained Mozilla bundle; retain hostname and chain validation.
    return ssl.create_default_context(cafile=certifi.where())
