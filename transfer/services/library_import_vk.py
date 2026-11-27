"""VK playlist and track import persistence."""

from django.db import transaction

from ..models import LibraryPlaylist, LibraryTrack
from .common import TransferError
from .library_track_management import append_provider_track


def save_vk_playlist(profile, title, tracks, source_url):
    """Persist VK playlist metadata and its tracks atomically."""
    if not tracks:
        raise TransferError("VK не вернул композиции для импорта.")
    with transaction.atomic():
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title=title[:120] or "Импорт из VK",
            provider=LibraryPlaylist.Provider.VK,
            external_url=source_url,
            description=f"Импортировано из VK · {len(tracks)} композиций",
        )
        LibraryTrack.objects.bulk_create(
            [
                LibraryTrack(
                    playlist=playlist,
                    title=track.title[:180],
                    artist=track.artist[:180],
                    duration_ms=max(track.duration, 0) * 1000,
                    cover_url=track.cover_url,
                    external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
                    external_url=f"https://vk.ru/audio{track.owner_id}_{track.track_id}",
                    source_provider=LibraryPlaylist.Provider.VK,
                    position=index,
                )
                for index, track in enumerate(tracks)
            ]
        )
    return playlist, len(tracks)


def save_vk_track(profile, track, source_url, playlist=None):
    """Save a VK track as a standalone playlist or append it to an owned one."""
    with transaction.atomic():
        if playlist is None:
            playlist = LibraryPlaylist.objects.create(
                profile=profile,
                title=f"VK — {track.artist} — {track.title}"[:120],
                provider=LibraryPlaylist.Provider.VK,
                external_url=source_url,
                description="Импортирована отдельная аудиозапись VK",
            )
        elif playlist.profile_id != profile.pk:
            raise TransferError("Нельзя добавлять композицию в чужой плейлист.")
        append_provider_track(
            playlist,
            title=track.title,
            artist=track.artist,
            provider=LibraryPlaylist.Provider.VK,
            external_id=track.audio_id or f"{track.owner_id}_{track.track_id}",
            external_url=source_url,
            duration_ms=max(0, track.duration) * 1000,
            cover_url=track.cover_url,
        )
    return playlist

def refresh_vk_track_metadata(playlist, vk_tracks):
    indexed = {f"{item.owner_id}_{item.track_id}": item for item in vk_tracks}
    updated = 0
    for track in playlist.tracks.all():
        base_id = "_".join(track.external_id.split("_")[:2])
        source = indexed.get(base_id)
        if not source:
            continue
        changed = []
        if source.cover_url and track.cover_url != source.cover_url:
            track.cover_url = source.cover_url
            changed.append("cover_url")
        if source.audio_id and track.external_id != source.audio_id:
            track.external_id = source.audio_id
            changed.append("external_id")
        if track.source_provider != LibraryPlaylist.Provider.VK:
            track.source_provider = LibraryPlaylist.Provider.VK
            changed.append("source_provider")
        if changed:
            track.save(update_fields=changed)
            updated += 1
    return updated



def import_vk_playlist(profile, client, source_url):
    """Fetch one public VK playlist and persist its local representation."""
    title, tracks = client.fetch_playlist(source_url)
    return save_vk_playlist(profile, title, tracks, source_url)


def import_vk_track(profile, client, source_url, playlist=None):
    """Fetch one VK track and save it as a playlist or append it to one."""
    track = client.fetch_track(source_url)
    return save_vk_track(profile, track, source_url, playlist=playlist), track


def refresh_vk_playlist_artwork(playlist, client):
    """Refresh provider metadata for an existing VK playlist."""
    _title, tracks = client.fetch_playlist(playlist.external_url)
    return refresh_vk_track_metadata(playlist, tracks)
