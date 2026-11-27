from types import SimpleNamespace

from django.test import TestCase

from ..models import LibraryPlaylist, LibraryProfile
from ..services import TransferError
from ..services.library_imports import (
    save_soundcloud_playlist,
    save_spotify_playlist,
    save_vk_playlist,
    spotify_resource_id,
    validate_soundcloud_permalink,
)


class LibraryImportServiceTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="f" * 64)

    def test_spotify_resource_id_accepts_only_expected_resource_links(self):
        resource_id = "A" * 22
        self.assertEqual(
            spotify_resource_id(f"https://open.spotify.com/playlist/{resource_id}", "playlist"),
            resource_id,
        )
        with self.assertRaises(ValueError):
            spotify_resource_id(f"https://open.spotify.com.attacker.example/playlist/{resource_id}", "playlist")
        with self.assertRaises(ValueError):
            spotify_resource_id(f"https://open.spotify.com:8443/playlist/{resource_id}", "playlist")

    def test_soundcloud_permalink_rejects_host_suffix_and_invalid_port(self):
        valid = "https://soundcloud.com/artist/track"
        self.assertEqual(validate_soundcloud_permalink(valid), valid)
        with self.assertRaises(ValueError):
            validate_soundcloud_permalink("https://soundcloud.com.attacker.example/artist/track")
        with self.assertRaises(ValueError):
            validate_soundcloud_permalink("https://soundcloud.com:8443/artist/track")

    def test_empty_spotify_payload_rolls_back_playlist_creation(self):
        before = self.profile.playlists.count()
        with self.assertRaises(TransferError):
            save_spotify_playlist(self.profile, {"name": "Empty"}, [], "https://open.spotify.com/playlist/" + "A" * 22)
        self.assertEqual(self.profile.playlists.count(), before)

    def test_empty_soundcloud_payload_rolls_back_playlist_creation(self):
        before = self.profile.playlists.count()
        with self.assertRaises(TransferError):
            save_soundcloud_playlist(
                self.profile,
                {"title": "Empty"},
                [{"id": 1, "title": ""}],
                "https://soundcloud.com/artist/empty",
            )
        self.assertEqual(self.profile.playlists.count(), before)

    def test_soundcloud_payload_keeps_track_when_duration_is_malformed(self):
        playlist, count = save_soundcloud_playlist(
            self.profile,
            {"title": "Imported"},
            [{
                "id": 42,
                "title": "Usable track",
                "duration": True,
                "user": {"username": "Uploader"},
            }],
            "https://soundcloud.com/artist/track",
        )
        track = playlist.tracks.get()
        self.assertEqual(count, 1)
        self.assertEqual(track.duration_ms, None)
        self.assertEqual(track.artist, "Uploader")

    def test_vk_playlist_persists_order_and_provider_metadata(self):
        tracks = [
            SimpleNamespace(
                title="First",
                artist="Artist",
                duration=120,
                cover_url="https://cdn.example/cover.jpg",
                audio_id="10_1",
                owner_id=10,
                track_id=1,
            ),
            SimpleNamespace(
                title="Second",
                artist="Artist",
                duration=90,
                cover_url="",
                audio_id="",
                owner_id=10,
                track_id=2,
            ),
        ]
        playlist, count = save_vk_playlist(self.profile, "VK list", tracks, "https://vk.ru/music")
        saved = list(playlist.tracks.all())
        self.assertEqual(count, 2)
        self.assertEqual([track.position for track in saved], [0, 1])
        self.assertEqual(saved[0].external_id, "10_1")
        self.assertEqual(saved[0].source_provider, LibraryPlaylist.Provider.VK)
