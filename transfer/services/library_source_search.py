"""Provider result mapping for the library's cross-provider search."""

from urllib.parse import quote_plus

from .library_source_links import safe_provider_source_url


def spotify_library_search_results(tracks):
    """Convert Spotify search payloads into the library's stable result shape."""
    results = []
    for track in tracks or []:
        if not isinstance(track, dict):
            continue
        external_urls = track.get("external_urls")
        external_url = (
            safe_provider_source_url(external_urls.get("spotify"), "spotify")
            if isinstance(external_urls, dict)
            else ""
        )
        if not external_url:
            continue
        artists = track.get("artists")
        if not isinstance(artists, list):
            artists = []
        artist = ", ".join(
            str(item.get("name") or "")
            for item in artists
            if isinstance(item, dict) and item.get("name")
        )
        album = track.get("album")
        images = album.get("images") if isinstance(album, dict) else []
        if not isinstance(images, list):
            images = []
        cover = images[0].get("url", "") if images and isinstance(images[0], dict) else ""
        results.append({
            "provider": "spotify",
            "id": str(track.get("id") or ""),
            "title": str(track.get("name") or ""),
            "artist": artist,
            "cover": cover,
            "url": external_url,
            "playable": True,
        })
    return results


def soundcloud_library_search_results(tracks, fallback_artist=""):
    """Convert SoundCloud search payloads into the library's stable result shape."""
    results = []
    for track in tracks or []:
        if not isinstance(track, dict):
            continue
        external_url = safe_provider_source_url(track.get("permalink_url"), "soundcloud")
        if not external_url:
            continue
        user = track.get("user")
        if not isinstance(user, dict):
            user = {}
        results.append({
            "provider": "soundcloud",
            "id": str(track.get("id") or ""),
            "title": str(track.get("title") or ""),
            "artist": str(user.get("username") or fallback_artist),
            "cover": str(track.get("artwork_url") or ""),
            "url": external_url,
            "playable": True,
        })
    return results


def external_music_search_result(provider, query):
    """Build a search-only result for providers without an integrated search API."""
    destinations = {
        "youtube_music": (
            "https://music.youtube.com/search?q=",
            "YouTube Music",
        ),
        "apple_music": (
            "https://music.apple.com/search?term=",
            "Apple Music",
        ),
    }
    try:
        base_url, label = destinations[provider]
    except KeyError as exc:
        raise ValueError("Unsupported external music provider.") from exc
    return {
        "provider": provider,
        "title": f"Открыть поиск в {label}",
        "artist": query,
        "cover": "",
        "url": base_url + quote_plus(query),
        "playable": False,
        "search_only": True,
    }
