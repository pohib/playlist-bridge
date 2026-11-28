"""Privacy-conscious, best-effort audit records for staff authentication."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.crypto import salted_hmac

from transfer.models import AdminAuditEvent

logger = logging.getLogger(__name__)


def _fingerprint(value):
    return salted_hmac(
        "transfer.staff-auth-audit",
        value or "unknown",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def _ip_address(request):
    # In production the reverse proxy overwrites X-Real-IP. Never trust
    # X-Forwarded-For supplied by the client.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown"


def _staff_account_for_login(username):
    user_model = get_user_model()
    field_name = user_model.USERNAME_FIELD
    lookup = {f"{field_name}__iexact": (username or "").strip()[:254], "is_staff": True}
    return user_model.objects.filter(**lookup).only("pk").first()


def _record_safely(**event):
    try:
        AdminAuditEvent.objects.create(**event)
    except Exception:
        # Authentication must not fail because the optional audit write failed.
        logger.exception("Unable to persist staff authentication audit event")


def record_staff_login_failure(request, username, *, throttled=False):
    """Record failed attempts only when the supplied identifier belongs to staff."""
    try:
        target = _staff_account_for_login(username)
        if target is None:
            return
        _record_safely(
            actor=None,
            action="auth.login_throttled" if throttled else "auth.login_failed",
            target_type=get_user_model()._meta.label,
            target_id=str(target.pk),
            metadata={
                "ip_fingerprint": _fingerprint(_ip_address(request)),
                "username_fingerprint": _fingerprint((username or "").strip().casefold()),
                "reason": "rate_limited" if throttled else "invalid_credentials",
            },
        )
    except Exception:
        logger.exception("Unable to prepare staff authentication audit event")


def record_staff_login_success(request, user):
    if not user.is_staff:
        return
    _record_safely(
        actor=user,
        action="auth.login_succeeded",
        target_type=get_user_model()._meta.label,
        target_id=str(user.pk),
        metadata={"ip_fingerprint": _fingerprint(_ip_address(request))},
    )
