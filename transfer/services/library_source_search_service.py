"""Request-independent orchestration for cross-provider library search."""

from .common import TransferError
from .library_source_search import (
    external_music_search_result,
    soundcloud_library_search_results,
    spotify_library_search_results,
)

ALLOWED_SEARCH_PROVIDERS = {
    "auto", "vk", "spotify", "soundcloud", "youtube_music", "apple_music",
}


class LibrarySourceSearchError(ValueError):
    """Invalid client input for library source search."""


def parse_library_source_search_request(payload):
    if not isinstance(payload, dict):
        raise LibrarySourceSearchError("Некорректный формат запроса.")
    title = str(payload.get("title") or "").strip()
    artist = str(payload.get("artist") or "").strip()
    requested = payload.get("providers", ["auto"])
    if not title or len(title) > 180 or len(artist) > 180:
        raise LibrarySourceSearchError(
            "Укажи название трека и корректного исполнителя."
        )
    if not isinstance(requested, list) or not requested or any(
        not isinstance(item, str) or item not in ALLOWED_SEARCH_PROVIDERS
        for item in requested
    ):
        raise LibrarySourceSearchError("Выбраны неподдерживаемые источники.")
    providers = (
        ["spotify", "soundcloud", "youtube_music", "apple_music"]
        if "auto" in requested
        else list(dict.fromkeys(requested))
    )
    return title, artist, providers


def search_library_sources(
    title, artist, providers, *, spotify_access, soundcloud_access
):
    """Query connected providers and return normalized results plus per-provider status."""
    query = f"{artist} {title}".strip()
    results = []
    statuses = {}
    for provider in providers:
        try:
            if provider == "vk":
                statuses[provider] = (
                    "VK используется для воспроизведения импортированных композиций; "
                    "поиск по каталогу VK через анонимный API недоступен."
                )
            elif provider == "spotify":
                client, token = spotify_access()
                results.extend(
                    spotify_library_search_results(client.search_tracks(token, query))
                )
                statuses[provider] = "ok"
            elif provider == "soundcloud":
                client, token = soundcloud_access()
                results.extend(
                    soundcloud_library_search_results(
                        client.search_tracks(token, query),
                        fallback_artist=artist,
                    )
                )
                statuses[provider] = "ok"
            elif provider in {"youtube_music", "apple_music"}:
                results.append(external_music_search_result(provider, query))
                statuses[provider] = (
                    "Доступна ссылка на поиск; публичный API для получения результатов "
                    "не подключён."
                )
        except TransferError as exc:
            statuses[provider] = str(exc)
        except (AttributeError, KeyError, TypeError, ValueError):
            statuses[provider] = "Провайдер вернул данные неизвестного формата."
    return {"results": results[:60], "statuses": statuses, "query": query}
