"""SoundCloud playlist, track, and library import endpoints."""

from urllib.parse import urlparse

from django.contrib import messages
from django.views.decorators.http import require_POST

from .library_support import _profile, _soundcloud_access
from .models import LibraryPlaylist, LibraryTrack
from .services import TransferError

def _validate_soundcloud_permalink(value):
    parsed = urlparse((value or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "soundcloud.com", "www.soundcloud.com", "m.soundcloud.com",
    } or parsed.port not in (None, 443) or not parsed.path or parsed.username or parsed.password:
        raise ValueError("Укажи публичную HTTPS-ссылку на soundcloud.com.")
    return parsed.geturl()


def _save_soundcloud_playlist(profile, resource, tracks, source_url):
    title = str(resource.get("title") or "SoundCloud playlist")[:120]
    playlist = LibraryPlaylist.objects.create(
        profile=profile,
        title=title,
        provider=LibraryPlaylist.Provider.SOUNDCLOUD,
        external_url=source_url,
        description=f"Импортировано из SoundCloud · {len(tracks)} композиций",
    )
    rows = []
    for index, item in enumerate(tracks):
        if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
            continue
        user = item.get("user")
        if not isinstance(user, dict):
            user = {}
        try:
            raw_duration = item.get("duration")
            if isinstance(raw_duration, bool):
                raise TypeError("Boolean duration is invalid.")
            parsed_duration = max(0, int(raw_duration or 0))
            duration_ms = parsed_duration if parsed_duration <= 2_147_483_647 else None
        except (TypeError, ValueError, OverflowError):
            # A malformed duration must not leave an empty playlist behind or
            # discard otherwise usable track metadata.
            duration_ms = None
        rows.append(LibraryTrack(
            playlist=playlist,
            title=str(item.get("title") or "Unknown track")[:180],
            artist=str(item.get("metadata_artist") or user.get("username") or "Unknown artist")[:180],
            duration_ms=duration_ms,
            external_id=str(item.get("id"))[:200],
            external_url=str(item.get("permalink_url") or "")[:2048],
            position=index,
        ))
    if not rows:
        playlist.delete()
        raise TransferError("SoundCloud не вернул доступные композиции.")
    LibraryTrack.objects.bulk_create(rows)
    return playlist, len(rows)


@require_POST
def import_soundcloud_playlist(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "playlist" and "tracks" not in resource:
            raise TransferError("Ссылка ведёт не на плейлист SoundCloud.")
        resource_id = resource.get("id")
        tracks = client.playlist_tracks(token, resource_id) if resource_id else resource.get("tracks", [])
        playlist, count = _save_soundcloud_playlist(_profile(request), resource, tracks, source_url)
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортирован плейлист «{playlist.title}»: {count} композиций.")
    return redirect("library")


@require_POST
def import_soundcloud_track(request):
    source_url = request.POST.get("source_url", "").strip()
    try:
        source_url = _validate_soundcloud_permalink(source_url)
        client, token = _soundcloud_access(request)
        resource = client.resolve(token, source_url)
        if resource.get("kind") != "track" and "duration" not in resource:
            raise TransferError("Ссылка ведёт не на трек SoundCloud.")
        profile = _profile(request)
        playlist, _count = _save_soundcloud_playlist(
            profile,
            {"title": f"SoundCloud — {resource.get('title') or 'Track'}"},
            [resource],
            source_url,
        )
    except (ValueError, TransferError) as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Композиция добавлена в библиотеку: {playlist.title}.")
    return redirect("library")


@require_POST
def import_soundcloud_library(request):
    try:
        client, token = _soundcloud_access(request)
        resources = client.my_playlists(token)
        profile = _profile(request)
        imported = 0
        track_count = 0
        for resource in resources[:30]:
            resource_id = resource.get("id")
            if not resource_id:
                continue
            tracks = client.playlist_tracks(token, resource_id)
            source_url = resource.get("permalink_url") or ""
            if source_url:
                _save_soundcloud_playlist(profile, resource, tracks, source_url)
                imported += 1
                track_count += len(tracks)
    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("library")
    messages.success(request, f"Импортировано плейлистов: {imported}; композиций: {track_count}.")
    return redirect("library")
