"""Fetch and cache the current UTC date from an internet time API.

The cached date is used for trial-expiry checks so users can't bypass
the trial by changing their device clock. Falls back to device time
if the network request fails.
"""

import logging
import threading
from datetime import date, datetime, timezone

log = logging.getLogger(__name__)

_cached_date: date | None = None
_fetch_lock = threading.Lock()
_fetch_started = False

_API_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"


def _fetch() -> None:
    global _cached_date
    try:
        import urllib.request
        with urllib.request.urlopen(_API_URL, timeout=5) as resp:
            import json
            data = json.loads(resp.read().decode())
            dt_str = data.get("datetime", "")
            _cached_date = datetime.fromisoformat(dt_str).astimezone(timezone.utc).date()
            log.info("Internet date fetched: %s", _cached_date)
    except Exception as exc:
        log.warning("Failed to fetch internet time: %s", exc)


def init() -> None:
    """Kick off a background fetch. Safe to call multiple times."""
    global _fetch_started
    with _fetch_lock:
        if _fetch_started:
            return
        _fetch_started = True
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()


def today() -> date:
    """Return the cached internet date, or device date if unavailable."""
    if _cached_date is not None:
        return _cached_date
    return date.today()
