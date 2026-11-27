from unittest.mock import Mock

from django.test import SimpleTestCase

from transfer.services.common import TransferError
from transfer.services.library_source_search_service import (
    LibrarySourceSearchError,
    parse_library_source_search_request,
    search_library_sources,
)


class LibrarySourceSearchRequestTests(SimpleTestCase):
    def test_auto_selects_supported_search_providers(self):
        self.assertEqual(
            parse_library_source_search_request({"title": "Track", "artist": "Artist"}),
            ("Track", "Artist", ["spotify", "soundcloud", "youtube_music", "apple_music"]),
        )

    def test_explicit_providers_are_deduplicated(self):
        self.assertEqual(
            parse_library_source_search_request({
                "title": "Track",
                "artist": "Artist",
                "providers": ["spotify", "spotify", "vk"],
            }),
            ("Track", "Artist", ["spotify", "vk"]),
        )

    def test_rejects_invalid_payloads_and_providers(self):
        for payload in (
            [],
            {"title": "", "artist": "Artist"},
            {"title": "x" * 181, "artist": "Artist"},
            {"title": "Track", "artist": "Artist", "providers": []},
            {"title": "Track", "artist": "Artist", "providers": ["unknown"]},
            {"title": "Track", "artist": "Artist", "providers": ["spotify", 1]},
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises(LibrarySourceSearchError),
            ):
                parse_library_source_search_request(payload)


class LibrarySourceSearchOrchestrationTests(SimpleTestCase):
    def test_queries_connected_providers_and_builds_external_search_links(self):
        spotify = Mock()
        spotify.search_tracks.return_value = [{
            "id": "track-id",
            "name": "Track",
            "artists": [{"name": "Artist"}],
            "external_urls": {"spotify": "https://open.spotify.com/track/abc"},
        }]
        soundcloud = Mock()
        soundcloud.search_tracks.return_value = [{
            "id": 123,
            "title": "Track",
            "permalink_url": "https://soundcloud.com/artist/track",
            "user": {"username": "Artist"},
        }]
        result = search_library_sources(
            "Track",
            "Artist",
            ["spotify", "soundcloud", "youtube_music"],
            spotify_access=lambda: (spotify, "spotify-token"),
            soundcloud_access=lambda: (soundcloud, "soundcloud-token"),
        )

        self.assertEqual(result["query"], "Artist Track")
        self.assertEqual(
            [item["provider"] for item in result["results"]],
            ["spotify", "soundcloud", "youtube_music"],
        )
        self.assertEqual(result["statuses"]["spotify"], "ok")
        self.assertEqual(result["statuses"]["soundcloud"], "ok")
        spotify.search_tracks.assert_called_once_with("spotify-token", "Artist Track")
        soundcloud.search_tracks.assert_called_once_with("soundcloud-token", "Artist Track")

    def test_provider_errors_are_isolated_to_provider_status(self):
        result = search_library_sources(
            "Track",
            "Artist",
            ["spotify", "apple_music"],
            spotify_access=lambda: (_ for _ in ()).throw(
                TransferError("Spotify needs reconnect")
            ),
            soundcloud_access=lambda: (None, None),
        )
        self.assertEqual(result["results"][0]["provider"], "apple_music")
        self.assertEqual(
            result["statuses"]["spotify"],
            "Не удалось выполнить поиск в этом сервисе. Проверь подключение и повтори попытку.",
        )
