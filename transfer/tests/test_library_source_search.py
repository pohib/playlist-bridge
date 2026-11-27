from django.test import SimpleTestCase

from transfer.services.library_source_search import (
    external_music_search_result,
    soundcloud_library_search_results,
    spotify_library_search_results,
)


class LibrarySourceSearchMappingTests(SimpleTestCase):
    def test_spotify_results_keep_existing_shape_and_reject_untrusted_links(self):
        results = spotify_library_search_results([
            {
                "id": "spotify-track",
                "name": "Track",
                "artists": [{"name": "Artist"}, {"name": "Guest"}],
                "album": {"images": [{"url": "https://cdn.example/cover.jpg"}]},
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/spotify-track",
                },
            },
            {
                "id": "spoofed",
                "name": "Spoofed",
                "external_urls": {
                    "spotify": "https://open.spotify.com.attacker.example/track/x",
                },
            },
            None,
        ])

        self.assertEqual(results, [{
            "provider": "spotify",
            "id": "spotify-track",
            "title": "Track",
            "artist": "Artist, Guest",
            "cover": "https://cdn.example/cover.jpg",
            "url": "https://open.spotify.com/track/spotify-track",
            "playable": True,
        }])

    def test_spotify_mapping_handles_malformed_nested_fields(self):
        results = spotify_library_search_results([{
            "id": "track",
            "name": "Track",
            "artists": "invalid",
            "album": {"images": "invalid"},
            "external_urls": {"spotify": "https://open.spotify.com/track/track"},
        }])

        self.assertEqual(results[0]["artist"], "")
        self.assertEqual(results[0]["cover"], "")

    def test_soundcloud_results_use_fallback_artist_and_validate_permalink(self):
        results = soundcloud_library_search_results([
            {
                "id": 123,
                "title": "Track",
                "user": {},
                "permalink_url": "https://soundcloud.com/artist/track",
            },
            {
                "id": 456,
                "title": "Unsafe",
                "permalink_url": "https://soundcloud.com.attacker.example/track",
            },
        ], fallback_artist="Original artist")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "123")
        self.assertEqual(results[0]["artist"], "Original artist")
        self.assertTrue(results[0]["playable"])

    def test_external_provider_search_links_are_encoded_and_search_only(self):
        youtube = external_music_search_result(
            "youtube_music",
            "Artist & Track",
        )
        apple = external_music_search_result("apple_music", "Artist & Track")

        self.assertEqual(
            youtube["url"],
            "https://music.youtube.com/search?q=Artist+%26+Track",
        )
        self.assertEqual(
            apple["url"],
            "https://music.apple.com/search?term=Artist+%26+Track",
        )
        self.assertFalse(youtube["playable"])
        self.assertTrue(youtube["search_only"])
        self.assertEqual(youtube["artist"], "Artist & Track")

    def test_external_provider_builder_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            external_music_search_result("unknown", "Track")
