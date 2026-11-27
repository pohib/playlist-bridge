"""API health and provider-connection status endpoints."""
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from ..oauth_views import connected_providers, encryption_key_is_valid


@never_cache
@require_GET
def api_status(request):
    spotify_connected, vk_connected, soundcloud_connected = connected_providers(request)
    return JsonResponse({
        "api_version": "1",
        "spotify_connected": spotify_connected,
        "vk_connected": vk_connected,
        "soundcloud_connected": soundcloud_connected,
        "soundcloud_configured": bool(settings.SOUNDCLOUD_CLIENT_ID and settings.SOUNDCLOUD_CLIENT_SECRET),
        "spotify_configured": bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET),
        "vk_configured": True,
        "encryption_key_configured": encryption_key_is_valid(),
    })
