"""UTC estimate anchored to elapsed time, with retryable network refresh."""

import logging
import json
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

from network_utils import tls_context

log = logging.getLogger(__name__)

_lock = threading.Lock()
_anchor_utc = None
_anchor_monotonic = None
_fetch_in_progress = False
_last_attempt = None
_REFRESH_SECONDS = 3600
_RETRY_SECONDS = 60

_API_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"


def _elapsed():
    # Android elapsedRealtime includes deep sleep; CLOCK_MONOTONIC does not.
    try:
        from kivy.utils import platform
        if platform == "android":
            from jnius import autoclass
            return autoclass("android.os.SystemClock").elapsedRealtime() / 1000
    except Exception:
        pass
    return time.monotonic()


def set_verified_time(instant):
    """Anchor a fresh authenticated backend timestamp, correcting device clocks."""
    global _anchor_utc, _anchor_monotonic
    if instant.tzinfo is None:
        raise ValueError("Verified time must have a timezone")
    with _lock:
        _anchor_utc = instant.astimezone(timezone.utc)
        _anchor_monotonic = _elapsed()


def _fetch() -> None:
    global _anchor_utc, _anchor_monotonic, _fetch_in_progress
    try:
        with urllib.request.urlopen(_API_URL, timeout=5, context=tls_context()) as resp:
            data = json.loads(resp.read(65536).decode())
        instant = datetime.fromisoformat(data["datetime"])
        if instant.tzinfo is None:
            raise ValueError("Time service returned a naive timestamp")
        with _lock:
            _anchor_utc = instant.astimezone(timezone.utc)
            _anchor_monotonic = _elapsed()
    except Exception:
        log.warning("Internet time unavailable; keeping the last UTC estimate")
    finally:
        with _lock:
            _fetch_in_progress = False


def init(force=False) -> None:
    """Refresh in the background; failures can retry after one minute."""
    global _fetch_in_progress, _last_attempt
    current = _elapsed()
    with _lock:
        interval = _REFRESH_SECONDS if _anchor_utc else _RETRY_SECONDS
        if _fetch_in_progress or (not force and _last_attempt is not None
                                  and current - _last_attempt < interval):
            return
        _fetch_in_progress = True
        _last_attempt = current
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()


def utcnow():
    """Advance a successful reading across midnight and app suspension."""
    with _lock:
        if _anchor_utc is not None:
            return _anchor_utc + timedelta(seconds=max(0, _elapsed() - _anchor_monotonic))
    return datetime.now(timezone.utc)


def today() -> date:
    return utcnow().date()
