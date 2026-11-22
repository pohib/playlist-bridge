from django.db.models import Count

from .credentials import get_session_fingerprint
from .models import LibraryPlaylist, LibraryProfile, OAuthCredential


def library_workspace(request):
    fingerprint = get_session_fingerprint(request)
    profile, _ = LibraryProfile.objects.get_or_create(session_fingerprint=fingerprint)
    credentials = set(
        OAuthCredential.objects.filter(session_fingerprint=fingerprint)
        .values_list("provider", flat=True)
    )
    playlists = (
        LibraryPlaylist.objects.filter(profile=profile)
        .annotate(track_count=Count("tracks"))
        .prefetch_related("tracks")
    )
    return {
        "library_profile": profile,
        "library_playlists": playlists,
        "library_playlist_count": playlists.count(),
        "library_track_count": sum(playlist.track_count for playlist in playlists),
        "library_vk_connected": "vk" in credentials,
        "library_spotify_connected": "spotify" in credentials,
        "library_soundcloud_connected": "soundcloud" in credentials,
    }
