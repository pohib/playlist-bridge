"""Capture a narrow allowlist of security-relevant user actions without request payloads."""
import logging
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from transfer.models import UserSecurityEvent

logger = logging.getLogger(__name__)

AUDITED_ROUTE_NAMES = {
    "library", "playlist_detail", "connections", "transfers", "profile",
    "password_change", "spotify_login", "spotify_callback", "disconnect_spotify",
    "soundcloud_login", "soundcloud_callback", "disconnect_soundcloud",
    "transfer_playlist", "library_update_profile", "library_import_vk",
    "library_import_vk_track", "library_refresh_vk_artwork",
    "library_import_spotify_playlist", "library_import_spotify_track",
    "library_import_spotify_library", "library_import_soundcloud_playlist",
    "library_import_soundcloud_track", "library_upload_soundcloud_track",
    "library_import_soundcloud_library", "library_transfer_playlist",
    "transfer_review", "open_transfer_target", "open_transfer_candidate",
    "search_transfer_item", "select_transfer_candidate", "skip_transfer_item",
    "library_open_playlist_source", "library_open_track_source",
    "library_create_playlist", "library_merge_playlists", "library_upload_local_track",
    "library_update_playlist", "library_add_track", "library_move_track",
    "library_update_track", "library_delete_playlist", "library_delete_track",
    "library_track_search", "api_create_transfer",
}
OBJECT_ARGUMENTS = (
    ("playlist_id", "playlist"), ("track_id", "track"),
    ("transfer_id", "transfer"), ("job_id", "transfer_job"),
    ("profile_id", "library_profile"), ("item_id", "transfer_item"),
)


class SecurityActivityMiddleware:
    """Persist route-level metadata after authentication; never inspect request payloads."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.security_audit_started = perf_counter()
        request.security_audit_id = uuid4()
        response = self.get_response(request)
        response.headers.setdefault("X-Request-ID", str(request.security_audit_id))
        return self.process_response(request, response)

    def process_response(self, request, response):
        match = getattr(request, "resolver_match", None)
        route_name = getattr(match, "url_name", "") or ""
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or route_name not in AUDITED_ROUTE_NAMES:
            return response

        kwargs = getattr(match, "kwargs", {}) or {}
        object_type, object_id = "", ""
        for argument, label in OBJECT_ARGUMENTS:
            if argument in kwargs:
                object_type, object_id = label, str(kwargs[argument])[:80]
                break
        referer_host = urlsplit(request.META.get("HTTP_REFERER", "")).hostname or ""
        started = getattr(request, "security_audit_started", perf_counter())
        request_id = getattr(request, "security_audit_id", uuid4())
        try:
            UserSecurityEvent.objects.create(
                user=user,
                username_snapshot=user.get_username()[:254],
                event_type=UserSecurityEvent.EventType.USER_ACTIVITY,
                ip_address=(request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "")[:45],
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
                http_method=request.method[:10],
                route_name=route_name[:100],
                response_status=response.status_code,
                request_id=request_id,
                duration_ms=min(2147483647, max(0, int((perf_counter() - started) * 1000))),
                object_type=object_type,
                object_id=object_id,
                referer_host=referer_host[:255],
            )
        except Exception:
            logger.exception("Unable to persist user activity event")
        return response
