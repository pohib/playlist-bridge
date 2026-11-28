"""SoundCloud OAuth authorization-code flow with PKCE."""
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
    started_at = time.perf_counter()
    try:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        request.session["soundcloud_oauth_state"] = state
        request.session["soundcloud_code_verifier"] = verifier
        return redirect(client_factory().authorization_url(state, verifier))
    except TransferError as exc:
        record_integration_failure(
            provider="soundcloud",
            operation="oauth_login",
            error=exc,
            user=request.user,
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        request.session["oauth_error"] = "Не удалось начать авторизацию SoundCloud."
        return redirect(provider_redirect(request))


def callback(request, *, client_factory, rotate_session_binding, store_credential):
    expected = request.session.pop("soundcloud_oauth_state", None)
    verifier = request.session.pop("soundcloud_code_verifier", None)
    received = request.GET.get("state", "")
    if (
        request.GET.get("error")
        or not expected
        or not verifier
        or not secrets.compare_digest(expected, received)
    ):
        request.session["oauth_error"] = (
            "Авторизация SoundCloud отменена или OAuth state недействителен."
        )
        return redirect(provider_redirect(request))
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "SoundCloud не вернул код авторизации."
        return redirect(provider_redirect(request))
    started_at = time.perf_counter()
    try:
        client = client_factory()
        token = client.exchange_code(code, verifier)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(
            get_session_fingerprint(request),
            "soundcloud",
            token,
            str(profile.get("id", "")),
        )
        request.session["oauth_success"] = (
            "SoundCloud успешно подключён. Токены сохранены в зашифрованном виде."
        )
    except TransferError as exc:
        record_integration_failure(
            provider="soundcloud",
            operation="oauth_callback",
            error=exc,
            user=request.user,
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        logger.warning("SoundCloud OAuth callback failed")
        request.session["oauth_error"] = "Не удалось завершить авторизацию SoundCloud."
    return redirect(provider_redirect(request))


def disconnect(request, *, client_factory, get_access_token_fn, delete_credential):
    fingerprint = get_session_fingerprint(request)
    try:
        client = client_factory()
        token, _ = get_access_token_fn(fingerprint, "soundcloud", client)
        client.disconnect(token)
    except TransferError:
        logger.info("SoundCloud disconnect revocation could not be confirmed")
    delete_credential(fingerprint, "soundcloud")
    request.session["oauth_success"] = "SoundCloud отключён."
    return redirect(provider_redirect(request))
