"""Spotify OAuth authorization-code flow."""

import logging
import secrets
import time

from django.shortcuts import redirect

from ..services import TransferError
from ..services.credential_service import get_session_fingerprint
from ..services.integration_event_recorder import record_integration_failure
from .shared import provider_redirect

logger = logging.getLogger(__name__)


def login(request, *, client_factory):
    try:
        state = secrets.token_urlsafe(32)
        request.session["spotify_oauth_state"] = state
        return redirect(client_factory().authorization_url(state))
    except TransferError as exc:
        record_integration_failure(
            provider="spotify",
            operation="oauth_login",
            error=exc,
            user=request.user,
        )
        request.session["oauth_error"] = "Не удалось начать авторизацию Spotify."
        return redirect(provider_redirect(request))


def callback(request, *, client_factory, rotate_session_binding, store_credential):
    expected = request.session.pop("spotify_oauth_state", None)
    received = request.GET.get("state", "")
    if (
        request.GET.get("error")
        or not expected
        or not secrets.compare_digest(expected, received)
    ):
        request.session["oauth_error"] = (
            "Авторизация Spotify отменена или OAuth state недействителен."
        )
        return redirect(provider_redirect(request))
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "Spotify не вернул код авторизации."
        return redirect(provider_redirect(request))
    try:
        client = client_factory()
        token = client.exchange_code(code)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(
            get_session_fingerprint(request),
            "spotify",
            token,
            profile.get("id", ""),
        )
        request.session["oauth_success"] = (
            "Spotify успешно подключён. Токены сохранены в зашифрованном виде."
        )
    except TransferError as exc:
        record_integration_failure(
            provider="spotify",
            operation="oauth_callback",
            error=exc,
            user=request.user,
        )
        logger.warning("Spotify OAuth callback failed")
        request.session["oauth_error"] = "Не удалось завершить авторизацию Spotify."
    return redirect(provider_redirect(request))


def disconnect(request, *, delete_credential):
    delete_credential(get_session_fingerprint(request), "spotify")
    request.session["oauth_success"] = "Spotify отключён."
    return redirect(provider_redirect(request))
