"""Unauthenticated server-side music catalog search adapters.

These endpoints are used only for discovery. They do not grant playback or
playlist-write access to Spotify, SoundCloud, Apple Music, or YouTube.
"""
import re

import requests
from django.core.cache import cache

from redis.exceptions import RedisError

SEARCH_CACHE_SECONDS = 10 * 60
REQUEST_TIMEOUT = (3.05, 7)
RESULT_LIMIT = 8
USER_AGENT = "PlaylistBridge/1.0 (music catalog search)"


def _cached(provider, query, loader):
    key = f"free_music_search:v1:{provider}:{query.casefold()}"
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except (RedisError, OSError, TimeoutError):
        cached = None
    results = loader()
    try:
        cache.set(key, results, SEARCH_CACHE_SECONDS)
    except (RedisError, OSError, TimeoutError):
        return results
    return results


def _itunes_search(query):
    response = requests.get(
        "https://itunes.apple.com/search",
        params={"term": query, "entity": "song", "limit": RESULT_LIMIT},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    results = []
    for item in payload.get("results", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        url = item.get("trackViewUrl")
        if not isinstance(url, str) or not url.startswith(("https://music.apple.com/", "https://itunes.apple.com/")):
            continue
        title, artist = item.get("trackName"), item.get("artistName")
        if not isinstance(title, str) or not title.strip() or not isinstance(artist, str):
            continue
        results.append({
            "provider": "itunes",
            "title": title[:180],
            "artist": artist[:180],
            "cover": item.get("artworkUrl100", "") if isinstance(item.get("artworkUrl100"), str) else "",
            "url": url,
            "playable": False,
        })
    return results[:RESULT_LIMIT]


def _deezer_search(query):
    response = requests.get(
        "https://api.deezer.com/search",
        params={"q": query, "limit": RESULT_LIMIT},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Deezer catalog returned an error")
    results = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        artist = item.get("artist")
        artist_name = artist.get("name") if isinstance(artist, dict) else ""
        url, title = item.get("link"), item.get("title")
        if not isinstance(url, str) or not url.startswith("https://www.deezer.com/") and not url.startswith("https://deezer.com/"):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        album = item.get("album")
        cover = album.get("cover_medium") if isinstance(album, dict) else ""
        results.append({
            "provider": "deezer",
            "title": title[:180],
            "artist": str(artist_name or "")[:180],
            "cover": cover if isinstance(cover, str) else "",
            "url": url,
            "playable": False,
        })
    return results[:RESULT_LIMIT]


def _youtube_music_search(query):
    from ytmusicapi import YTMusic

    payload = YTMusic().search(query, filter="songs", limit=RESULT_LIMIT)
    results = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or item.get("resultType") not in (None, "song"):
            continue
        video_id = item.get("videoId")
        title = item.get("title")
        if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id) or not isinstance(title, str) or not title.strip():
            continue
        artists = item.get("artists")
        artist = ", ".join(
            entry.get("name", "") for entry in artists
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        ) if isinstance(artists, list) else ""
        thumbnails = item.get("thumbnails")
        cover = thumbnails[-1].get("url", "") if isinstance(thumbnails, list) and thumbnails and isinstance(thumbnails[-1], dict) else ""
        results.append({
            "provider": "youtube_music",
            "title": title[:180],
            "artist": artist[:180],
            "cover": cover if isinstance(cover, str) else "",
            "url": f"https://music.youtube.com/watch?v={video_id}",
            "playable": False,
        })
    return results[:RESULT_LIMIT]


def search_free_music_catalogs(query, providers):
    """Search free public catalogs independently; one provider failure won't stop others."""
    loaders = {
        "itunes": _itunes_search,
        "deezer": _deezer_search,
        "youtube_music": _youtube_music_search,
    }
    results, statuses = [], {}
    for provider in providers:
        loader = loaders.get(provider)
        if loader is None:
            continue
        try:
            provider_results = _cached(provider, query, lambda loader=loader: loader(query))
            results.extend(provider_results)
            statuses[provider] = f"Найдено: {len(provider_results)}" if provider_results else "Совпадений не найдено."
        except (requests.RequestException, ValueError, ImportError, OSError, TimeoutError, TypeError, KeyError):
            statuses[provider] = "Бесплатный каталог временно недоступен. Попробуй позже."
    return results[:24], statuses
