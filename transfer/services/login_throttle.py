"""Distributed throttling for password authentication attempts."""
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils.crypto import salted_hmac

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 15 * 60
PAIR_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 30


def _digest(value):
    return salted_hmac("transfer.login-throttle", value, secret=settings.SECRET_KEY, algorithm="sha256").hexdigest()


def _keys(request, username):
    # REMOTE_ADDR is deliberately used instead of X-Forwarded-For: clients must
    # not be able to bypass throttling by supplying their own forwarding header.
    # Nginx overwrites X-Real-IP from Cloudflare's connecting-IP header in production.
    remote_addr = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown"
    normalized_username = (username or "").strip().casefold()[:254]
    pair = _digest(f"{remote_addr}\0{normalized_username}")
    ip = _digest(remote_addr)
    return f"login-throttle:pair:{pair}", f"login-throttle:ip:{ip}"


def _increment(key):
    if cache.add(key, 1, timeout=WINDOW_SECONDS):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # The key may expire between add() and incr().
        cache.add(key, 1, timeout=WINDOW_SECONDS)
        return 1


def login_is_throttled(request, username):
    pair_key, ip_key = _keys(request, username)
    return (
        (cache.get(pair_key) or 0) >= PAIR_FAILURE_LIMIT
        or (cache.get(ip_key) or 0) >= IP_FAILURE_LIMIT
    )


def record_login_failure(request, username):
    pair_key, ip_key = _keys(request, username)
    _increment(pair_key)
    _increment(ip_key)


def clear_login_failures(request, username):
    pair_key, _ip_key = _keys(request, username)
    cache.delete(pair_key)
