from types import SimpleNamespace

from django.test import TestCase

from ..models import LibraryPlaylist, LibraryProfile
from ..services import (
    TransferError,
    library_import_soundcloud,
    library_import_spotify,
    library_import_vk,
)
from ..services.library_imports import (
    refresh_vk_track_metadata,
    save_soundcloud_playlist,
    save_soundcloud_track,
    save_spotify_playlist,
    save_spotify_track,
    save_vk_playlist,
    save_vk_track,
    spotify_resource_id,
    validate_soundcloud_permalink,
)


class LibraryImportServiceTests(TestCase):
    def test_compatibility_facade_reexports_provider_specific_services(self):
        self.assertIs(save_spotify_playlist, library_import_spotify.save_spotify_playlist)
        self.assertIs(save_spotify_track, library_import_spotify.save_spotify_track)
        self.assertIs(spotify_resource_id, library_import_spotify.spotify_resource_id)
        self.assertIs(save_soundcloud_playlist, library_import_soundcloud.save_soundcloud_playlist)
        self.assertIs(save_soundcloud_track, library_import_soundcloud.save_soundcloud_track)
        self.assertIs(validate_soundcloud_permalink, library_import_soundcloud.validate_soundcloud_permalink)
        self.assertIs(save_vk_playlist, library_import_vk.save_vk_playlist)
        self.assertIs(save_vk_track, library_import_vk.save_vk_track)
        self.assertIs(refresh_vk_track_metadata, library_import_vk.refresh_vk_track_metadata)

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


    def test_spotify_track_service_appends_normalized_metadata_to_existing_playlist(self):
        playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Existing",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        source_url = "https://open.spotify.com/track/" + "A" * 22
        saved_playlist = save_spotify_track(
            self.profile,
            {
                "id": "spotify-track",
                "name": "Imported track",
                "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                "album": {"name": "Album", "images": []},
                "duration_ms": 123000,
                "external_urls": {"spotify": source_url},
            },
            source_url,
            playlist=playlist,
        )

        self.assertIs(saved_playlist, playlist)
        track = playlist.tracks.get()
        self.assertEqual(track.title, "Imported track")
        self.assertEqual(track.artist, "Artist A, Artist B")
        self.assertEqual(track.album, "Album")
        self.assertEqual(track.external_id, "spotify-track")
        self.assertEqual(track.duration_ms, 123000)
        self.assertEqual(track.source_provider, LibraryPlaylist.Provider.SPOTIFY)

    def test_spotify_track_service_creates_a_single_track_playlist(self):
        source_url = "https://open.spotify.com/track/" + "B" * 22
        playlist = save_spotify_track(
            self.profile,
            {
                "id": "spotify-single",
                "name": "Single",
                "type": "track",
                "artists": [{"name": "Artist"}],
                "duration_ms": 90000,
            },
            source_url,
        )

        self.assertEqual(playlist.provider, LibraryPlaylist.Provider.SPOTIFY)
        self.assertEqual(playlist.tracks.get().external_id, "spotify-single")

    def test_soundcloud_track_service_appends_provider_metadata_to_existing_playlist(self):
        playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Existing",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        source_url = "https://soundcloud.com/artist/track"
        saved_playlist = save_soundcloud_track(
            self.profile,
            {
                "id": 42,
                "title": "SoundCloud track",
                "metadata_artist": "Original artist",
                "user": {"username": "Uploader"},
                "duration": 120000,
                "permalink_url": source_url,
                "artwork_url": "",
            },
            source_url,
            playlist=playlist,
        )

        self.assertIs(saved_playlist, playlist)
        track = playlist.tracks.get()
        self.assertEqual(track.title, "SoundCloud track")
        self.assertEqual(track.artist, "Original artist")
        self.assertEqual(track.external_id, "42")
        self.assertEqual(track.duration_ms, 120000)
        self.assertEqual(track.source_provider, LibraryPlaylist.Provider.SOUNDCLOUD)

    def test_soundcloud_track_service_creates_a_single_track_playlist(self):
        source_url = "https://soundcloud.com/artist/single"
        playlist = save_soundcloud_track(
            self.profile,
            {
                "id": 43,
                "title": "Single",
                "duration": 60000,
                "permalink_url": source_url,
            },
            source_url,
        )

        self.assertEqual(playlist.provider, LibraryPlaylist.Provider.SOUNDCLOUD)
        self.assertEqual(playlist.tracks.get().external_id, "43")

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
