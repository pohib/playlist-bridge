"""Provider search-result normalization for manual transfer review."""


def _duration_ms(value):
    """Return a safe non-negative duration or zero for malformed provider data."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def normalize_spotify_search_results(results, safe_candidate_url):
    """Map Spotify API payloads to the stable candidate shape stored on review items."""
    candidates = []
    for result in results or []:
        if not isinstance(result, dict) or not result.get("id") or not result.get("uri"):
            continue
        external_urls = result.get("external_urls")
        if not isinstance(external_urls, dict):
            external_urls = {}
        artists = result.get("artists")
        if not isinstance(artists, list):
            artists = []
        artist_names = [
            str(artist.get("name") or "")
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ]
        candidates.append({
            "id": str(result.get("id") or ""),
            "uri": str(result.get("uri") or ""),
            "title": str(result.get("name") or "")[:180],
            "artist": ", ".join(artist_names)[:180],
            "duration_ms": _duration_ms(result.get("duration_ms")),
            "url": safe_candidate_url(external_urls.get("spotify", ""), "spotify"),
        })
    return candidates[:10]


def normalize_soundcloud_search_results(results, safe_candidate_url):
    """Map SoundCloud API payloads to the stable candidate shape stored on review items."""
    candidates = []
    for result in results or []:
        if not isinstance(result, dict) or not result.get("id"):
            continue
        user = result.get("user")
        if not isinstance(user, dict):
            user = {}
        artist = result.get("metadata_artist") or user.get("username") or ""
        candidates.append({
            "id": str(result.get("id") or ""),
            "uri": str(result.get("urn") or result.get("id") or ""),
            "title": str(result.get("title") or "")[:180],
            "artist": str(artist)[:180],
            "duration_ms": _duration_ms(result.get("duration")),
            "url": safe_candidate_url(result.get("permalink_url"), "soundcloud"),
        })
    return candidates[:10]
