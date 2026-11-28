"""Request-independent orchestration for free queue discovery search."""

from .free_music_catalog_search import search_free_music_catalogs

ALLOWED_SEARCH_PROVIDERS = {"auto", "deezer", "itunes", "youtube_music"}
DEFAULT_FREE_PROVIDERS = ["deezer", "itunes", "youtube_music"]


class LibrarySourceSearchError(ValueError):
    """Invalid client input for library source search."""


def parse_library_source_search_request(payload):
    if not isinstance(payload, dict):
        raise LibrarySourceSearchError("Некорректный формат запроса.")
    title = str(payload.get("title") or "").strip()
    artist = str(payload.get("artist") or "").strip()
    requested = payload.get("providers", ["auto"])
    if not title or len(title) > 180 or len(artist) > 180:
        raise LibrarySourceSearchError("Укажи название трека и корректного исполнителя.")
    if not isinstance(requested, list) or not requested or any(
        not isinstance(item, str) or item not in ALLOWED_SEARCH_PROVIDERS for item in requested
    ):
        raise LibrarySourceSearchError("Выбраны неподдерживаемые источники.")
    providers = DEFAULT_FREE_PROVIDERS if "auto" in requested else list(dict.fromkeys(requested))
    return title, artist, providers


def search_library_sources(title, artist, providers):
    """Search public catalogs without Spotify/SoundCloud OAuth or paid app credentials."""
    query = f"{artist} {title}".strip()
    results, statuses = search_free_music_catalogs(query, providers)
    return {"results": results[:60], "statuses": statuses, "query": query}
