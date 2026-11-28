"""Safe recording and classification of provider/worker failures."""
# ruff: noqa: I001
import re
from urllib.parse import urlsplit

from django.db import DatabaseError

from ..models import ProviderIntegrationEvent


_SECRET_PATTERN = re.compile(
    r"(?i)\\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|passwd|authorization|proxy-authorization|cookie|set-cookie|api[_-]?key)\\b[\\\"']?"
    r"(\\s*[:=]\\s*)(?:Bearer\\s+\\S+|Basic\\s+\\S+|\\\"[^\\\"]*\\\"|'[^']*'|[^\\s,;}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\\b(Bearer|Basic)\\s+[A-Za-z0-9._~+/-]+=*")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|client_secret|api_key|key)=)[^&#\\s]+"
)


def sanitize_integration_message(value):
    """Remove common credential forms and URL query strings before persistence."""
    message = str(value or "Неизвестная ошибка")
    message = _SECRET_PATTERN.sub(r"\\1\\2[скрыто]", message)
    message = _BEARER_PATTERN.sub(r"\\1 [скрыто]", message)
    message = _QUERY_SECRET_PATTERN.sub(r"\\1[скрыто]", message)
    message = re.sub(
        r"(https?://[^\\s?#]+)\\?[^\\s#]+",
        r"\\1?[параметры скрыты]",
        message,
        flags=re.IGNORECASE,
    )
    return message[:500]


def _extract_http_status(error):
    """Find a valid HTTP status in an exception or its wrapped causes."""
    pending = [error]
    visited = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        response = getattr(current, "response", None)
        candidates = (
            getattr(response, "status_code", None),
            getattr(current, "status_code", None),
        )
        for candidate in candidates:
            try:
                status = int(candidate)
            except (TypeError, ValueError):
                continue
            if 100 <= status <= 599:
                return status
        pending.extend((getattr(current, "__cause__", None), getattr(current, "__context__", None)))
    return None


def classify_integration_error(error):
    """Return a stable category without storing raw exception payloads."""
    name = error.__class__.__name__.casefold()
    message = str(error).casefold()
    if any(token in name for token in ("timeout", "connection", "network")) or any(
        token in message for token in ("timeout", "timed out", "connection", "сеть", "соединен")
    ):
        return ProviderIntegrationEvent.Category.NETWORK
    if "429" in message or "rate limit" in message or "частот" in message or "квот" in message:
        return ProviderIntegrationEvent.Category.RATE_LIMIT
    if any(token in message for token in ("oauth", "token", "авторизац", "доступ запрещ")):
        return ProviderIntegrationEvent.Category.AUTH
    if any(token in name for token in ("validation", "valueerror")):
        return ProviderIntegrationEvent.Category.VALIDATION
    return ProviderIntegrationEvent.Category.PROVIDER


def infer_provider(error, source_url=""):
    message = str(error).casefold()
    host = (urlsplit(source_url).hostname or "").casefold()
    if "soundcloud" in message or "soundcloud" in host:
        return ProviderIntegrationEvent.Provider.SOUNDCLOUD
    if "spotify" in message:
        return ProviderIntegrationEvent.Provider.SPOTIFY
    if "vk" in message or host.endswith(("vk.com", "vk.ru")):
        return ProviderIntegrationEvent.Provider.VK
    return ProviderIntegrationEvent.Provider.TRANSFER


def record_integration_failure(
    *, provider, operation, error, user=None, job=None, category=None,
    status_code=None, duration_ms=None,
):
    """Store a redacted provider failure without disrupting the original operation."""
    try:
        authenticated_user = user if getattr(user, "is_authenticated", False) else None
        if status_code is None:
            status_code = _extract_http_status(error)
        if status_code is not None:
            try:
                status_code = int(status_code)
            except (TypeError, ValueError):
                status_code = None
            if status_code is not None and not 100 <= status_code <= 599:
                status_code = None
        if duration_ms is not None:
            try:
                duration_ms = max(0, min(int(duration_ms), 2_147_483_647))
            except (TypeError, ValueError):
                duration_ms = None
        return ProviderIntegrationEvent.objects.create(
            provider=provider,
            operation=str(operation)[:80],
            category=category or classify_integration_error(error),
            severity=ProviderIntegrationEvent.Severity.ERROR,
            message=sanitize_integration_message(error),
            status_code=status_code,
            duration_ms=duration_ms,
            transfer_job=job,
            user=authenticated_user,
        )
    except DatabaseError:
        return None


def record_transfer_failure(*, job, error):
    """Persist a redacted transfer failure and associate it with its source provider."""
    return record_integration_failure(
        provider=infer_provider(error, job.source_url),
        operation="run_transfer",
        error=error,
        job=job,
    )


def record_worker_failure(*, job_id, error, operation):
    """Record a sanitized Celery dispatch/recovery failure without masking it."""
    from ..models import TransferJob

    try:
        job = TransferJob.objects.filter(pk=job_id).first()
    except DatabaseError:
        return None
    return record_integration_failure(
        provider=ProviderIntegrationEvent.Provider.TRANSFER,
        operation=operation,
        error=error,
        job=job,
        category=ProviderIntegrationEvent.Category.WORKER,
    )
