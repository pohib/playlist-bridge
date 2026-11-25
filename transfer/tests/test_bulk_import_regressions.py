from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from ..credentials import get_session_fingerprint
from ..models import LibraryPlaylist, LibraryProfile
from ..services import TransferError


class BulkLibraryImportRegressionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="bulk-import-regression-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )

    @staticmethod
    def spotify_track(track_id):
        return {
            "item": {
                "type": "track",
                "id": track_id,
                "name": f"Track {track_id}",
                "artists": [{"name": "Artist"}],
                "duration_ms": 120000,
            }
        }

    def test_spotify_library_import_caps_batch_and_continues_after_unavailable_playlist(self):
        resources = [{"id": "bad", "name": "Unavailable"}] + [
            {"id": f"playlist-{index}", "name": f"Playlist {index}", "external_urls": {}}
            for index in range(30)
        ]
        client = Mock()
        client.my_playlists.return_value = resources

        def playlist_items(_token, playlist_id):
            if playlist_id == "bad":
                raise TransferError("temporarily unavailable")
            return [self.spotify_track(playlist_id)]

        client.get_playlist_items.side_effect = playlist_items
        with patch("transfer.library_import_views._spotify_access", return_value=(client, "spotify-token")):
            response = self.client.post(reverse("library_import_spotify_library"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get_playlist_items.call_count, 30)
        self.assertEqual(
            self.profile.playlists.filter(provider=LibraryPlaylist.Provider.SPOTIFY).count(),
            29,
        )
        self.assertFalse(self.profile.playlists.filter(title="Unavailable").exists())

    def test_soundcloud_library_import_processes_at_most_thirty_playlists(self):
        resources = [
            {
                "id": index,
                "title": f"SoundCloud {index}",
                "permalink_url": f"https://soundcloud.com/artist/playlist-{index}",
            }
            for index in range(1, 32)
        ]
        client = Mock()
        client.my_playlists.return_value = resources
        client.playlist_tracks.return_value = [
            {
                "id": 9001,
                "title": "Track",
                "duration": 90000,
                "user": {"username": "Artist"},
            }
        ]

        with patch("transfer.library_import_views._soundcloud_access", return_value=(client, "sc-token")):
            response = self.client.post(reverse("library_import_soundcloud_library"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.playlist_tracks.call_count, 30)
        self.assertEqual(
            self.profile.playlists.filter(provider=LibraryPlaylist.Provider.SOUNDCLOUD).count(),
            30,
        )

    def test_soundcloud_library_import_keeps_prior_success_when_later_playlist_fails(self):
        resources = [
            {"id": 1, "title": "Imported", "permalink_url": "https://soundcloud.com/a/one"},
            {"id": 2, "title": "Unavailable", "permalink_url": "https://soundcloud.com/a/two"},
        ]
        client = Mock()
        client.my_playlists.return_value = resources
        client.playlist_tracks.side_effect = [
            [{"id": 10, "title": "Saved track", "duration": 1000}],
            TransferError("provider unavailable"),
        ]

        with patch("transfer.library_import_views._soundcloud_access", return_value=(client, "sc-token")):
            response = self.client.post(reverse("library_import_soundcloud_library"))

        self.assertEqual(response.status_code, 302)
        playlist = self.profile.playlists.get(title="Imported")
        self.assertEqual(playlist.tracks.count(), 1)
        self.assertFalse(self.profile.playlists.filter(title="Unavailable").exists())
