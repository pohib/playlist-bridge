from unittest.mock import Mock

from django.test import TestCase

from transfer.models import LibraryPlaylist, LibraryProfile
from transfer.services import TransferError, library_import_soundcloud, library_import_spotify


class SingleTrackImportWorkflowTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="s" * 64)

    def test_soundcloud_workflow_resolves_and_persists_track(self):
        client = Mock()
        source_url = "https://soundcloud.com/artist/track"
        client.resolve.return_value = {
            "kind": "track",
            "id": 42,
            "title": "Imported SoundCloud track",
            "duration": 120000,
            "permalink_url": source_url,
            "user": {"username": "Artist"},
        }

        playlist = library_import_soundcloud.import_soundcloud_track(
            self.profile, client, "access-token", source_url
        )

        client.resolve.assert_called_once_with("access-token", source_url)
        self.assertEqual(playlist.provider, LibraryPlaylist.Provider.SOUNDCLOUD)
        self.assertEqual(playlist.tracks.get().external_id, "42")

    def test_soundcloud_workflow_rejects_non_track_resource(self):
        client = Mock()
        client.resolve.return_value = {"kind": "playlist", "id": 7, "tracks": []}
        before = self.profile.playlists.count()

        with self.assertRaises(TransferError):
            library_import_soundcloud.import_soundcloud_track(
                self.profile,
                client,
                "access-token",
                "https://soundcloud.com/artist/playlist",
            )

        self.assertEqual(self.profile.playlists.count(), before)

    def test_spotify_workflow_fetches_and_persists_track(self):
        client = Mock()
        track_id = "A" * 22
        source_url = f"https://open.spotify.com/track/{track_id}"
        client.track_details.return_value = {
            "id": track_id,
            "name": "Imported Spotify track",
            "artists": [{"name": "Artist"}],
            "duration_ms": 180000,
        }

        playlist = library_import_spotify.import_spotify_track(
            self.profile, client, "access-token", source_url
        )

        client.track_details.assert_called_once_with("access-token", track_id)
        self.assertEqual(playlist.provider, LibraryPlaylist.Provider.SPOTIFY)
        self.assertEqual(playlist.tracks.get().external_id, track_id)

    def test_spotify_workflow_rejects_invalid_track_url_before_api_call(self):
        client = Mock()

        with self.assertRaises(ValueError):
            library_import_spotify.import_spotify_track(
                self.profile,
                client,
                "access-token",
                "https://open.spotify.com.attacker.example/track/" + "A" * 22,
            )

        client.track_details.assert_not_called()
