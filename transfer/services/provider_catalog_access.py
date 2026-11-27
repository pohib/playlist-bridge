"""App-scoped credentials for public music catalog search.

Tokens are shared through Redis between web and Celery processes. They are
separate from user OAuth credentials and are never used for account data/writes.
"""
import time
from hashlib import sha256

from django.conf import settings
from django.core.cache import cache

from .common import TransferError
from .credential_service import decrypt_payload, encrypt_payload
from .soundcloud_client import SoundCloudClient
from .spotify_client import SpotifyClient

TOKEN_CACHE_TTL = 12 * 60 * 60


def get_catalog_access(provider):
    """Return a provider client and cached app-scoped catalog token."""
    if provider == "spotify":
        client_id = settings.SPOTIFY_CLIENT_ID
        client_secret = settings.SPOTIFY_CLIENT_SECRET
        client = SpotifyClient(client_id, client_secret, settings.SPOTIFY_REDIRECT_URI)
    elif provider == "soundcloud":
        client_id = settings.SOUNDCLOUD_CLIENT_ID
        client_secret = settings.SOUNDCLOUD_CLIENT_SECRET
        client = SoundCloudClient(client_id, client_secret, settings.SOUNDCLOUD_REDIRECT_URI)
    else:
        raise TransferError("Поиск в этом музыкальном сервисе не поддерживается.")

    if not client_id or not client_secret:
        raise TransferError(
            f"Публичный поиск {provider} не настроен на сервере. "
            "Пользовательское подключение не требуется."
        )

    credential_fingerprint = sha256(
        f"{provider}:{client_id}:{client_secret}".encode()
    ).hexdigest()[:20]
    cache_key = f"catalog_token:{credential_fingerprint}"
    cached_value = cache.get(cache_key)
    try:
        cached = decrypt_payload(cached_value) if cached_value else None
    except TransferError:
        cache.delete(cache_key)
        cached = None
    now = time.time()

    if isinstance(cached, dict):
        access_token = cached.get("access_token")
        expires_at = cached.get("expires_at", 0)
        if isinstance(access_token, str) and access_token and expires_at > now + 60:
            return client, access_token
        refresh_token = cached.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token and provider == "soundcloud":
            try:
                token_data = client.refresh_token(refresh_token)
            except TransferError:
                token_data = client.client_credentials_token()
        else:
            token_data = client.client_credentials_token()
    else:
        token_data = client.client_credentials_token()

    access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise TransferError(f"{provider} не выдал токен публичного поиска.")

    try:
        expires_in = int(token_data.get("expires_in", 3600))
    except (TypeError, ValueError, OverflowError):
        expires_in = 3600
    cache.set(
        cache_key,
        encrypt_payload({
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": now + max(60, expires_in),
        }),
        timeout=TOKEN_CACHE_TTL,
    )
    return client, access_token
