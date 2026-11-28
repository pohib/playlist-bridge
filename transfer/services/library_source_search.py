"""Compatibility helpers for outbound links returned by free catalog search."""

def external_music_search_result(provider, query):
    """Build a search-only result for a provider search page."""
    from urllib.parse import quote_plus
    destinations = {
        "youtube_music": ("https://music.youtube.com/search?q=", "YouTube Music"),
        "apple_music": ("https://music.apple.com/search?term=", "Apple Music"),
    }
    try:
        base_url, label = destinations[provider]
    except KeyError as exc:
        raise ValueError("Unsupported external music provider.") from exc
    return {
        "provider": provider, "title": f"Открыть поиск в {label}",
        "artist": query, "cover": "", "url": base_url + quote_plus(query),
        "playable": False, "search_only": True,
    }
