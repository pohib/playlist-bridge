import logging
import secrets
import time

from cryptography.fernet import Fernet
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .credentials import delete_credential, get_access_token, get_session_fingerprint, store_credential
from .models import LibraryProfile, OAuthCredential, TransferJob
from .services import SoundCloudClient, SpotifyClient, TransferError

logger = logging.getLogger(__name__)


def encryption_key_is_valid():
    try:
        Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
        return True
    except (ValueError, AttributeError):
        return False


def spotify_client():
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        raise TransferError("Spotify OAuth не настроен на сервере.")
    return SpotifyClient(
        settings.SPOTIFY_CLIENT_ID,
        settings.SPOTIFY_CLIENT_SECRET,
        settings.SPOTIFY_REDIRECT_URI,
    )


def soundcloud_client():
    if not settings.SOUNDCLOUD_CLIENT_ID or not settings.SOUNDCLOUD_CLIENT_SECRET:
        raise TransferError("SoundCloud OAuth не настроен на сервере.")
    return SoundCloudClient(settings.SOUNDCLOUD_CLIENT_ID, settings.SOUNDCLOUD_CLIENT_SECRET, settings.SOUNDCLOUD_REDIRECT_URI)


def rotate_session_binding(request):
    old_fingerprint = get_session_fingerprint(request)
    request.session.cycle_key()
    new_fingerprint = get_session_fingerprint(request)
    OAuthCredential.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)
    TransferJob.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)
    LibraryProfile.objects.filter(session_fingerprint=old_fingerprint).update(session_fingerprint=new_fingerprint)


def connected_providers(request):
    fingerprint = get_session_fingerprint(request)
    providers = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint)
        .values_list("provider", flat=True)
    )
    return "spotify" in providers, False, "soundcloud" in providers


@never_cache
@require_GET
def spotify_login(request):
    try:
        state = secrets.token_urlsafe(32)
        request.session["spotify_oauth_state"] = state
        return redirect(spotify_client().authorization_url(state))
    except TransferError as exc:
        request.session["oauth_error"] = str(exc)
        return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def spotify_callback(request):
    expected = request.session.pop("spotify_oauth_state", None)
    received = request.GET.get("state", "")
    if request.GET.get("error") or not expected or not secrets.compare_digest(expected, received):
        request.session["oauth_error"] = "Авторизация Spotify отменена или OAuth state недействителен."
        return redirect("connections" if request.user.is_authenticated else "home")
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "Spotify не вернул код авторизации."
        return redirect("connections" if request.user.is_authenticated else "home")
    try:
        client = spotify_client()
        token = client.exchange_code(code)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(get_session_fingerprint(request), "spotify", token, profile.get("id", ""))
        request.session["oauth_success"] = "Spotify успешно подключён. Токены сохранены в зашифрованном виде."
    except TransferError as exc:
        logger.warning("Spotify OAuth callback failed: %s", exc)
        request.session["oauth_error"] = "Не удалось завершить авторизацию Spotify."
    return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def soundcloud_login(request):
    try:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        request.session["soundcloud_oauth_state"] = state
        request.session["soundcloud_code_verifier"] = verifier
        return redirect(soundcloud_client().authorization_url(state, verifier))
    except TransferError as exc:
        request.session["oauth_error"] = str(exc)
        return redirect("connections" if request.user.is_authenticated else "home")


@never_cache
@require_GET
def soundcloud_callback(request):
    expected = request.session.pop("soundcloud_oauth_state", None)
    verifier = request.session.pop("soundcloud_code_verifier", None)
    received = request.GET.get("state", "")
    if request.GET.get("error") or not expected or not verifier or not secrets.compare_digest(expected, received):
        request.session["oauth_error"] = "Авторизация SoundCloud отменена или OAuth state недействителен."
        return redirect("connections" if request.user.is_authenticated else "home")
    code = request.GET.get("code", "")
    if not code:
        request.session["oauth_error"] = "SoundCloud не вернул код авторизации."
        return redirect("connections" if request.user.is_authenticated else "home")
    try:
        client = soundcloud_client()
        token = client.exchange_code(code, verifier)
        token["obtained_at"] = time.time()
        profile = client.current_user(token["access_token"])
        rotate_session_binding(request)
        store_credential(get_session_fingerprint(request), "soundcloud", token, str(profile.get("id", "")))
        request.session["oauth_success"] = "SoundCloud успешно подключён. Токены сохранены в зашифрованном виде."
    except TransferError as exc:
        logger.warning("SoundCloud OAuth callback failed: %s", exc)
        request.session["oauth_error"] = "Не удалось завершить авторизацию SoundCloud."
    return redirect("connections" if request.user.is_authenticated else "home")


@require_POST
def disconnect_soundcloud(request):
    fingerprint = get_session_fingerprint(request)
    try:
        client = soundcloud_client()
        token, _ = get_access_token(fingerprint, "soundcloud", client)
        client.disconnect(token)
    except TransferError:
        logger.info("SoundCloud disconnect revocation could not be confirmed")
    delete_credential(fingerprint, "soundcloud")
    request.session["oauth_success"] = "SoundCloud отключён."
    return redirect("connections" if request.user.is_authenticated else "home")


@require_POST
def disconnect_spotify(request):
    delete_credential(get_session_fingerprint(request), "spotify")
    request.session["oauth_success"] = "Spotify отключён."
    return redirect("connections" if request.user.is_authenticated else "home")


