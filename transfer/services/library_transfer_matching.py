"""Provider-specific matching for library-to-provider transfers.

The service owns candidate normalization, confidence thresholds and the
shape of persisted review candidates. HTTP handling and playlist persistence
remain in the view layer.
"""

import re
from types import SimpleNamespace

from .track_matcher import score_candidate

MATCH_THRESHOLD = 0.82
REVIEW_THRESHOLD = 0.45
MAX_REVIEW_CANDIDATES = 5


def _source_track(track):
    return SimpleNamespace(
        title=track.title,
        artist=track.artist,
        duration=(track.duration_ms or 0) // 1000,
    )


def match_spotify_tracks(tracks, *, client, token, safe_candidate_url):
    """Search Spotify and split confident matches from manual-review candidates."""
    matched = {}
    unmatched = []
    for track in tracks:
        ranked = sorted(
            (
                (score_candidate(_source_track(track), item), item)
                for item in client.search(token, track.artist, track.title)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if (
            ranked
            and ranked[0][0] >= MATCH_THRESHOLD
            and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(ranked[0][1].get("uri") or ""))
        ):
            item = ranked[0][1]
            matched[track.pk] = {
                "id": str(item.get("id") or ""),
                "uri": str(item.get("uri") or ""),
                "url": safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
            }
            continue

        candidates = [
            {
                "id": str(item.get("id") or ""),
                "uri": str(item.get("uri") or ""),
                "title": str(item.get("name") or "")[:180],
                "artist": ", ".join(str(artist.get("name") or "") for artist in item.get("artists", []))[:180],
                "duration_ms": int(item.get("duration_ms") or 0),
                "url": safe_candidate_url((item.get("external_urls") or {}).get("spotify", ""), "spotify"),
            }
            for score, item in ranked[:MAX_REVIEW_CANDIDATES]
            if score >= REVIEW_THRESHOLD
            and item.get("id")
            and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", str(item.get("uri") or ""))
        ]
        unmatched.append((track, candidates))
    return matched, unmatched


def match_soundcloud_tracks(tracks, *, client, token, safe_candidate_url):
    """Search SoundCloud and split confident matches from review candidates."""
    matched = {}
    unmatched = []
    for track in tracks:
        ranked = []
        source = _source_track(track)
        for candidate in client.search_tracks(token, f"{track.artist} {track.title}"):
            user = candidate.get("user") or {}
            normalized = {
                "name": candidate.get("title", ""),
                "artists": [{"name": candidate.get("metadata_artist") or user.get("username", "")}],
                "duration_ms": candidate.get("duration"),
            }
            ranked.append((score_candidate(source, normalized), candidate))
        ranked.sort(key=lambda pair: pair[0], reverse=True)

        if (
            ranked
            and ranked[0][0] >= MATCH_THRESHOLD
            and re.fullmatch(r"[0-9]+", str(ranked[0][1].get("id") or ""))
        ):
            candidate = ranked[0][1]
            matched[track.pk] = {
                "id": str(candidate["id"]),
                "url": safe_candidate_url(candidate.get("permalink_url"), "soundcloud"),
            }
            continue

        candidates = [
            {
                "id": str(candidate.get("id") or ""),
                "uri": str(candidate.get("urn") or candidate.get("id") or ""),
                "title": str(candidate.get("title") or "")[:180],
                "artist": str(candidate.get("metadata_artist") or (candidate.get("user") or {}).get("username") or "")[:180],
                "duration_ms": int(candidate.get("duration") or 0),
                "url": safe_candidate_url(candidate.get("permalink_url"), "soundcloud"),
            }
            for score, candidate in ranked[:MAX_REVIEW_CANDIDATES]
            if score >= REVIEW_THRESHOLD
            and re.fullmatch(r"[0-9]+", str(candidate.get("id") or ""))
        ]
        unmatched.append((track, candidates))
    return matched, unmatched
