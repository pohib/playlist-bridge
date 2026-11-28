"""Safe recording and classification of provider/worker failures."""
import re
from urllib.parse import urlsplit, urlunsplit

from django.db import DatabaseError

from ..models import ProviderIntegrationEvent


_SECRET_PATTERN = re.compile(
    r"(?i)\\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|passwd|authorization|proxy-authorization|cookie|set-cookie|api[_-]?key)\\b"
    r"(\\s*[:=]\\s*)(?:Bearer\\s+\\S+|Basic\\s+\\S+|\\"[^\\"]*\\"|'[^']*'|[^\\s,;]+)"
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
    if "vk" in message or host.endswith("vk.com") or host.endswith("vk.ru"):
        return ProviderIntegrationEvent.Provider.VK
    return ProviderIntegrationEvent.Provider.TRANSFER


def record_transfer_failure(*, job, error):
    """Persist only a redacted operational summary; never credentials or raw payloads."""
    try:
        category = classify_integration_error(error)
        message = sanitize_integration_message(error)
        provider = infer_provider(error, job.source_url)
        return ProviderIntegrationEvent.objects.create(
            provider=provider,
            operation="run_transfer",
            category=category,
            severity=ProviderIntegrationEvent.Severity.ERROR,
            message=message,
            transfer_job=job,
        )
    except DatabaseError:
        # Operational telemetry must never prevent the job from reaching a terminal state.
        return None
