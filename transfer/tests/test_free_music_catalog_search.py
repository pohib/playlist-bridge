from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from transfer.services.free_music_catalog_search import (
    _deezer_search, _itunes_search, _youtube_music_search,
)


class FreeCatalogAdapterTests(SimpleTestCase):
    @patch("transfer.services.free_music_catalog_search.requests.get")
    def test_itunes_normalizes_search_results(self, get):
        response = Mock()
        response.json.return_value = {"results": [{
            "trackName": "Song", "artistName": "Artist",
            "trackViewUrl": "https://music.apple.com/us/album/song/1",
            "artworkUrl100": "https://is1-ssl.mzstatic.com/image.jpg",
        }]}
        get.return_value = response
        result = _itunes_search("Artist Song")
        self.assertEqual(result[0]["provider"], "itunes")
        self.assertEqual(result[0]["title"], "Song")
        self.assertFalse(result[0]["playable"])
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["timeout"], (3.05, 7))

    @patch("transfer.services.free_music_catalog_search.requests.get")
    def test_deezer_normalizes_results_and_rejects_untrusted_link(self, get):
        response = Mock()
        response.json.return_value = {"data": [
            {"title": "Song", "link": "https://www.deezer.com/track/1",
             "artist": {"name": "Artist"}, "album": {"cover_medium": "https://cdn.example/cover.jpg"}},
            {"title": "Spoof", "link": "https://deezer.com.attacker.test/track/2"},
        ]}
        get.return_value = response
        result = _deezer_search("Artist Song")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["artist"], "Artist")

    @patch("transfer.services.free_music_catalog_search.YTMusic", create=True)
    def test_youtube_music_maps_song_result(self, ytmusic_class):
        # The module is imported lazily inside the adapter.
        import sys
        module = Mock()
        module.YTMusic.return_value.search.return_value = [{
            "resultType": "song", "videoId": "video123", "title": "Song",
            "artists": [{"name": "Artist"}], "thumbnails": [{"url": "https://img.example/cover.jpg"}],
        }]
        with patch.dict(sys.modules, {"ytmusicapi": module}):
            result = _youtube_music_search("Artist Song")
        self.assertEqual(result[0]["url"], "https://music.youtube.com/watch?v=video123")
        self.assertFalse(result[0]["playable"])
