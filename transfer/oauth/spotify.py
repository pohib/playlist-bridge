"""Spotify OAuth authorization-code flow."""

import logging
import secrets
import time

from django.shortcuts import redirect

from ..services import TransferError
from .shared import provider_redirect

logger = logging.getLogger(__name__)


def login(request, *, client_factory):
    try:
        state = secrets.token_urlsafe(32)
        request.session["spotify_oauth_state"] = state
        return redirect(client_factory().authorization_url(state))
    except TransferError as exc:
        request.session["oauth_error"] = str(exc)
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
            __import__("transfer.credentials", fromlist=["get_session_fingerprint"])
            .get_session_fingerprint(request),
            "spotify",
            token,
            profile.get("id", ""),
        )
        request.session["oauth_success"] = (
            "Spotify успешно подключён. Токены сохранены в зашифрованном виде."
        )
    except TransferError as exc:
        logger.warning("Spotify OAuth callback failed: %s", exc)
        request.session["oauth_error"] = "Не удалось завершить авторизацию Spotify."
    return redirect(provider_redirect(request))


def disconnect(request, *, delete_credential):
    from ..credentials import get_session_fingerprint

    delete_credential(get_session_fingerprint(request), "spotify")
    request.session["oauth_success"] = "Spotify отключён."
    return redirect(provider_redirect(request))
