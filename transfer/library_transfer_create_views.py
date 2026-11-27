"""Create a cross-provider transfer from a local library playlist."""

import logging
import re
from types import SimpleNamespace

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .credentials import get_access_token, get_session_fingerprint
from .library_support import _profile, _safe_candidate_url
from .models import LibraryPlaylist, LibraryTrack, LibraryTransfer, LibraryTransferItem
from .services import SoundCloudClient, SpotifyClient, TransferError, score_candidate

logger = logging.getLogger(__name__)

@require_POST
def transfer_library_playlist(request, playlist_id):
    playlist = get_object_or_404(
        LibraryPlaylist.objects.prefetch_related("tracks"),
        pk=playlist_id,
        profile=_profile(request),
    )
    target = request.POST.get("target_provider", "").strip()
    if target not in {"spotify", "soundcloud"}:
        messages.error(request, "Выбери поддерживаемый целевой сервис.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    tracks = list(playlist.tracks.all())
    if not tracks:
        messages.error(request, "В плейлисте нет композиций для переноса.")
        return redirect("playlist_detail", playlist_id=playlist.pk)
    if len(tracks) > 100:
        messages.error(request, "Пока можно переносить не более 100 композиций за один запуск.")
        return redirect("playlist_detail", playlist_id=playlist.pk)

    fingerprint = get_session_fingerprint(request)
    matched = {}
    unmatched = []
    try:
        if target == "spotify":
            client = SpotifyClient(
                settings.SPOTIFY_CLIENT_ID,
                settings.SPOTIFY_CLIENT_SECRET,
                settings.SPOTIFY_REDIRECT_URI,
            )
            token, _ = get_access_token(fingerprint, "spotify", client)
            for track in tracks:
                source = SimpleNamespace(
                    title=track.title,
                    artist=track.artist,
                    duration=(track.duration_ms or 0) // 1000,
                )
                ranked = sorted(
                    ((score_candidate(source, item), item) for item in client.search(token, track.artist, track.title)),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
                if ranked and ranked[0][0] >= 0.82 and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(ranked[0][1].get("uri") or "")):
                    item = ranked[0][1]
                    matched[track.pk] = {
                        "id": str(item.get("id") or ""),
                        "uri": str(item.get("uri") or ""),
                        "url": _safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
                    }
                else:
                    unmatched.append((track, [
                        {
                            "id": str(item.get("id") or ""),
                            "uri": str(item.get("uri") or ""),
                            "title": str(item.get("name") or "")[:180],
                            "artist": ", ".join(str(artist.get("name") or "") for artist in item.get("artists", []))[:180],
                            "duration_ms": int(item.get("duration_ms") or 0),
                            "url": _safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
                        }
                        for score, item in ranked[:5] if score >= 0.45 and item.get("id") and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(item.get("uri") or ""))
                    ]))
            uris = [
                matched[track.pk]["uri"]
                for track in tracks
                if track.pk in matched and matched[track.pk].get("uri")
            ]
            target_id = client.create_playlist(token, playlist.title) if uris else ""
            if target_id:
                client.add_items(token, target_id, uris)
            target_url = f"https://open.spotify.com/playlist/{target_id}" if target_id else ""
        else:
            client = SoundCloudClient(
                settings.SOUNDCLOUD_CLIENT_ID,
                settings.SOUNDCLOUD_CLIENT_SECRET,
                settings.SOUNDCLOUD_REDIRECT_URI,
            )
            token, _ = get_access_token(fingerprint, "soundcloud", client)
            for track in tracks:
                query = f"{track.artist} {track.title}"
                candidates = client.search_tracks(token, query)
                ranked = []
                source = SimpleNamespace(
                    title=track.title,
                    artist=track.artist,
                    duration=(track.duration_ms or 0) // 1000,
                )
                for candidate in candidates:
                    user = candidate.get("user") or {}
                    normalized = {
                        "name": candidate.get("title", ""),
                        "artists": [{"name": candidate.get("metadata_artist") or user.get("username", "")}],
                        "duration_ms": candidate.get("duration"),
                    }
                    ranked.append((score_candidate(source, normalized), candidate))
                ranked.sort(key=lambda pair: pair[0], reverse=True)
                if ranked and ranked[0][0] >= 0.82 and re.fullmatch(r"[0-9]+", str(ranked[0][1].get("id") or "")):
                    candidate = ranked[0][1]
                    matched[track.pk] = {
                        "id": str(candidate["id"]),
                        "url": _safe_candidate_url(candidate.get("permalink_url"), "soundcloud"),
                    }
                else:
                    unmatched.append((track, [
                        {
                            "id": str(candidate.get("id") or ""),
                            "uri": str(candidate.get("urn") or candidate.get("id") or ""),
                            "title": str(candidate.get("title") or "")[:180],
                            "artist": str(candidate.get("metadata_artist") or (candidate.get("user") or {}).get("username") or "")[:180],
                            "duration_ms": int(candidate.get("duration") or 0),
                            "url": _safe_candidate_url(candidate.get("permalink_url"), "soundcloud"),
                        }
                        for score, candidate in ranked[:5] if score >= 0.45 and re.fullmatch(r"[0-9]+", str(candidate.get("id") or ""))
                    ]))
            target_ids = [matched[track.pk]["id"] for track in tracks if track.pk in matched]
            if target_ids:
                result = client.create_playlist(token, playlist.title, target_ids)
                target_id = str(result["id"])
                target_url = _safe_candidate_url(result.get("permalink_url"), "soundcloud") or "https://soundcloud.com"
            else:
                target_id = ""
                target_url = ""

    except TransferError as exc:
        messages.error(request, str(exc))
        return redirect("playlist_detail", playlist_id=playlist.pk)

    target_playlist = LibraryPlaylist.objects.create(
        profile=playlist.profile,
        title=f"{playlist.title} · {target.title()}"[:120],
        provider=target,
        external_url=target_url,
        description=f"Перенос из библиотеки · найдено {len(matched)} из {len(tracks)}",
    )
    LibraryTrack.objects.bulk_create([
        LibraryTrack(
            playlist=target_playlist,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            external_id=matched[track.pk]["id"],
            external_url=matched[track.pk]["url"],
            position=index,
        )
        for index, track in enumerate(tracks) if track.pk in matched
    ])

    review = LibraryTransfer.objects.create(
        profile=playlist.profile,
        source_playlist=playlist,
        target_provider=target,
        target_playlist=target_playlist,
        provider_playlist_id=str(target_id),
        target_url=target_url,
        status=LibraryTransfer.Status.REVIEW if unmatched else LibraryTransfer.Status.COMPLETED,
        total=len(tracks),
        matched=len(matched),
        completed_at=timezone.now() if not unmatched else None,
    )
    pending_by_id = {track.pk: candidates for track, candidates in unmatched}
    LibraryTransferItem.objects.bulk_create([
        LibraryTransferItem(
            transfer=review,
            source_track=track,
            position=index,
            status=LibraryTransferItem.Status.MATCHED if track.pk in matched else LibraryTransferItem.Status.PENDING,
            candidates=pending_by_id.get(track.pk, []),
            target_external_id=matched.get(track.pk, {}).get("id", ""),
            target_url=matched.get(track.pk, {}).get("url", ""),
        )
        for index, track in enumerate(tracks)
    ])
    logger.info(
        "Library transfer created transfer_id=%s profile_id=%s target=%s total=%s matched=%s pending=%s",
        review.pk, playlist.profile_id, target, len(tracks), len(matched), len(unmatched),
    )
    messages.success(
        request,
        f"Создан плейлист {target.title()}: найдено {len(matched)} из {len(tracks)}. "
        f"Требуют ручного сопоставления: {len(unmatched)}.",
    )
    return redirect("transfer_review", transfer_id=review.pk)


