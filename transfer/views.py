"""Compatibility exports for the former combined views module.

New routes should import their handlers from oauth_views or api_views.
"""

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

__all__ = [
    "api_create_transfer", "api_error", "api_openapi", "api_status",
    "api_transfer_detail", "api_transfer_report", "connected_providers",
    "disconnect_soundcloud", "disconnect_spotify", "download_report",
    "encryption_key_is_valid", "healthz", "home", "rotate_session_binding",
    "serialize_job", "soundcloud_callback", "soundcloud_login",
    "spotify_callback", "spotify_login", "transfer_playlist", "SpotifyClient",
]

from .api_views import (
    api_create_transfer, api_error, api_openapi, api_status,
    api_transfer_detail, api_transfer_report, serialize_job,
)
from .services import SpotifyClient
from .oauth_views import (
    connected_providers, disconnect_soundcloud, disconnect_spotify,
    encryption_key_is_valid, rotate_session_binding, soundcloud_callback,
    soundcloud_client, soundcloud_login, spotify_callback, spotify_client,
    spotify_login,
)


@never_cache
@require_GET
def home(request):
    return render(request, "transfer/landing.html")


@never_cache
@require_GET
def healthz(request):
    return JsonResponse({"status": "ok"})


@require_POST
def transfer_playlist(request):
    return JsonResponse({"error": "Используй POST /api/v1/transfers/."}, status=410)


@require_GET
def download_report(request):
    return HttpResponse("Отчёт доступен через API задачи.", status=410)
