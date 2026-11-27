"""Backward-compatible URL view facade for provider OAuth flows."""
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import credentials
from .services.credential_service import (
    delete_credential,
    get_access_token,
    store_credential,
)
from .oauth import clients, shared, soundcloud, spotify

# Preserve the historical public import surface.
get_session_fingerprint = credentials.get_session_fingerprint
encryption_key_is_valid = shared.encryption_key_is_valid
rotate_session_binding = shared.rotate_session_binding
connected_providers = shared.connected_providers
spotify_client = clients.spotify_client
soundcloud_client = clients.soundcloud_client


@never_cache
@require_GET
def spotify_login(request):
    return spotify.login(request, client_factory=spotify_client)


@never_cache
@require_GET
def spotify_callback(request):
    return spotify.callback(request, client_factory=spotify_client, rotate_session_binding=rotate_session_binding, store_credential=store_credential)


@never_cache
@require_GET
def soundcloud_login(request):
    return soundcloud.login(request, client_factory=soundcloud_client)


@never_cache
@require_GET
def soundcloud_callback(request):
    return soundcloud.callback(request, client_factory=soundcloud_client, rotate_session_binding=rotate_session_binding, store_credential=store_credential)


@require_POST
def disconnect_soundcloud(request):
    return soundcloud.disconnect(request, client_factory=soundcloud_client, get_access_token_fn=get_access_token, delete_credential=delete_credential)


@require_POST
def disconnect_spotify(request):
    return spotify.disconnect(request, delete_credential=delete_credential)
