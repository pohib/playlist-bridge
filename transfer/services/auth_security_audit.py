"""Privacy-conscious authentication telemetry and staff audit records."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.crypto import salted_hmac

from transfer.models import AdminAuditEvent, UserSecurityEvent

logger = logging.getLogger(__name__)


def _fingerprint(value):
    return salted_hmac(
        "transfer.staff-auth-audit", value or "unknown",
        secret=settings.SECRET_KEY, algorithm="sha256",
    ).hexdigest()


def _ip_address(request):
    # The production reverse proxy overwrites X-Real-IP. Never trust X-Forwarded-For.
    return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "")[:45]


def _find_account(username):
    user_model = get_user_model()
    field_name = user_model.USERNAME_FIELD
    lookup = {f"{field_name}__iexact": (username or "").strip()[:254]}
    return user_model.objects.filter(**lookup).first()


def _record_security_event(request, *, user, username, event_type):
    try:
        UserSecurityEvent.objects.create(
            user=user,
            username_snapshot=user.get_username() if user else (username or "").strip()[:254],
            event_type=event_type,
            ip_address=_ip_address(request),
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
        )
    except Exception:
        logger.exception("Unable to persist user security event")


def _record_staff_audit(user, request, *, action, reason=None, username=None):
    if not user.is_staff:
        return
    metadata = {"ip_fingerprint": _fingerprint(_ip_address(request))}
    if reason:
        metadata.update({
            "username_fingerprint": _fingerprint((username or "").strip().casefold()),
            "reason": reason,
        })
    try:
        AdminAuditEvent.objects.create(
            actor=user if action == "auth.login_succeeded" else None,
            action=action,
            target_type=get_user_model()._meta.label,
            target_id=str(user.pk),
            metadata=metadata,
        )
    except Exception:
        logger.exception("Unable to persist staff authentication audit event")


def record_login_failure(request, username, *, throttled=False):
    """Record attempts for known accounts without exposing account existence to clients."""
    try:
        user = _find_account(username)
        if user is None:
            return
        event_type = (
            UserSecurityEvent.EventType.LOGIN_THROTTLED if throttled
            else UserSecurityEvent.EventType.LOGIN_FAILED
        )
        _record_security_event(request, user=user, username=username, event_type=event_type)
        _record_staff_audit(
            user, request,
            action="auth.login_throttled" if throttled else "auth.login_failed",
            reason="rate_limited" if throttled else "invalid_credentials",
            username=username,
        )
    except Exception:
        logger.exception("Unable to prepare authentication audit event")


def record_login_success(request, user):
    _record_security_event(
        request, user=user, username=user.get_username(),
        event_type=UserSecurityEvent.EventType.LOGIN_SUCCEEDED,
    )
    _record_staff_audit(user, request, action="auth.login_succeeded")
