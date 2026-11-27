"""Presentation helpers for library playlist and player views."""

from django.urls import reverse


def cover_proxy_url(track):
    """Return the same-origin cover URL for a track, if it has artwork."""
    if not track.cover_url:
        return ""
    return f"{reverse('library_cover_proxy')}?track_id={track.pk}"


def build_track_playback_data(track, playlist):
    """Serialize one library track into the player contract."""
    source_provider = track.source_provider or playlist.provider
    is_local = bool(track.audio_file)
    return {
        "provider": "local" if is_local else source_provider,
        "id": track.external_id,
        "url": (
            reverse("library_stream_local_track", kwargs={"track_id": track.pk})
            if is_local else track.external_url
        ),
        "title": track.title,
        "artist": track.artist,
        "cover": cover_proxy_url(track),
        "duration": track.duration_ms,
        "stream_url": (
            reverse("library_vk_track_audio", kwargs={"track_id": track.pk})
            if source_provider == "vk" and not is_local else ""
        ),
        "stream_resolve_url": (
            reverse("library_vk_track_stream", kwargs={"track_id": track.pk})
            if source_provider == "vk" and not is_local else ""
        ),
    }


def build_playlist_playback_tracks(playlist):
    """Build ordered playback data for a playlist detail page."""
    return [
        build_track_playback_data(track, playlist)
        for track in playlist.tracks.all()
    ]


def prepare_library_playlist(playlist):
    """Attach the player and artwork presentation fields used by the library page."""
    tracks = list(playlist.tracks.all())
    for track in tracks:
        track.cover_proxy_url = cover_proxy_url(track)

    playlist.playback_id = f"library-playback-{playlist.pk}"
    playlist.cover_proxy_url = next(
        (track.cover_proxy_url for track in tracks if track.cover_proxy_url),
        "",
    )
    playlist.playback_data = [
        build_track_playback_data(track, playlist)
        for track in tracks
    ]
    return playlist
