from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from ..credentials import get_session_fingerprint
from ..models import (
    LibraryPlaylist,
    LibraryProfile,
    LibraryTrack,
    LibraryTransfer,
    LibraryTransferItem,
)
from ..services import TransferError


class LibraryMutationRegressionTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="library-mutation-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        self.track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Existing",
            artist="Artist",
            position=0,
        )

    def test_create_playlist_trims_fields_and_persists_only_safe_http_url(self):
        response = self.client.post(
            reverse("library_create_playlist"),
            {
                "title": "  New collection  ",
                "description": "  Description  ",
                "provider": LibraryPlaylist.Provider.MANUAL,
                "external_url": "https://example.com/playlist",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = LibraryPlaylist.objects.get(title="New collection")
        self.assertEqual(created.description, "Description")
        self.assertEqual(created.external_url, "https://example.com/playlist")

    def test_create_playlist_rejects_unsafe_url_without_database_write(self):
        before = LibraryPlaylist.objects.count()

        response = self.client.post(
            reverse("library_create_playlist"),
            {
                "title": "Unsafe",
                "provider": LibraryPlaylist.Provider.MANUAL,
                "external_url": "javascript:alert(1)",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(LibraryPlaylist.objects.count(), before)

    def test_create_playlist_rejects_unknown_provider(self):
        before = LibraryPlaylist.objects.count()

        self.client.post(
            reverse("library_create_playlist"),
            {"title": "Unknown provider", "provider": "attacker"},
        )

        self.assertEqual(LibraryPlaylist.objects.count(), before)

    def test_add_track_converts_seconds_to_milliseconds_and_appends_position(self):
        response = self.client.post(
            reverse("library_add_track", kwargs={"playlist_id": self.playlist.pk}),
            {
                "title": "  New track ",
                "artist": " Artist ",
                "duration_seconds": "123.5",
            },
        )

        self.assertEqual(response.status_code, 302)
        added = self.playlist.tracks.get(title="New track")
        self.assertEqual(added.artist, "Artist")
        self.assertEqual(added.duration_ms, 123500)
        self.assertEqual(added.position, 1)

    def test_add_track_rejects_negative_or_excessive_duration(self):
        before = self.playlist.tracks.count()
        url = reverse("library_add_track", kwargs={"playlist_id": self.playlist.pk})

        for duration in ("-1", "86401", "not-a-number"):
            with self.subTest(duration=duration):
                self.client.post(
                    url,
                    {"title": "Invalid", "artist": "Artist", "duration_seconds": duration},
                )

        self.assertEqual(self.playlist.tracks.count(), before)

    def test_add_track_rejects_foreign_playlist(self):
        other_profile = LibraryProfile.objects.create(session_fingerprint="d" * 64)
        other_playlist = LibraryPlaylist.objects.create(profile=other_profile, title="Private")
        response = self.client.post(
            reverse("library_add_track", kwargs={"playlist_id": other_playlist.pk}),
            {"title": "Injected", "artist": "Attacker"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(other_playlist.tracks.exists())

    def test_delete_track_rejects_track_from_another_profile(self):
        other_profile = LibraryProfile.objects.create(session_fingerprint="e" * 64)
        other_playlist = LibraryPlaylist.objects.create(profile=other_profile, title="Private")
        other_track = LibraryTrack.objects.create(playlist=other_playlist, title="Private", artist="Owner")

        response = self.client.post(
            reverse("library_delete_track", kwargs={"track_id": other_track.pk})
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(LibraryTrack.objects.filter(pk=other_track.pk).exists())

    def test_local_upload_rejects_signature_mismatch_even_with_audio_mime(self):
        upload = SimpleUploadedFile(
            "spoofed.mp3",
            b"<html>not audio</html>",
            content_type="audio/mpeg",
        )
        before = LibraryTrack.objects.count()

        response = self.client.post(
            reverse("library_upload_local_track"),
            {"title": "Spoof", "artist": "Attacker", "audio_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(LibraryTrack.objects.count(), before)

    def test_local_upload_rejects_disallowed_extension(self):
        upload = SimpleUploadedFile("payload.exe", b"ID3" + b"\x00" * 20)
        before = LibraryTrack.objects.count()

        self.client.post(
            reverse("library_upload_local_track"),
            {"title": "Payload", "artist": "Attacker", "audio_file": upload},
        )

        self.assertEqual(LibraryTrack.objects.count(), before)


class ProviderImportWorkflowTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="provider-import-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )

    def test_spotify_playlist_import_rejects_invalid_url_before_oauth(self):
        with patch("transfer.library_import_views._spotify_access") as access:
            response = self.client.post(
                reverse("library_import_spotify_playlist"),
                {"source_url": "https://attacker.example/playlist/" + "A" * 22},
            )

        self.assertEqual(response.status_code, 302)
        access.assert_not_called()
        self.assertFalse(self.profile.playlists.exists())

    def test_spotify_playlist_import_preserves_track_metadata_and_order(self):
        client = Mock()
        client.api.return_value = {"name": "Imported Spotify"}
        client.get_playlist_items.return_value = [
            {
                "item": {
                    "type": "track",
                    "id": "spotify-track-1",
                    "name": "First",
                    "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                    "album": {"name": "Album"},
                    "duration_ms": 123000,
                    "external_urls": {"spotify": "https://open.spotify.com/track/" + "A" * 22},
                },
            },
            {
                "item": {
                    "type": "track",
                    "id": "spotify-track-2",
                    "name": "Second",
                    "artists": [{"name": "Artist C"}],
                    "duration_ms": 234000,
                },
            },
        ]

        with patch("transfer.library_import_views._spotify_access", return_value=(client, "token")):
            response = self.client.post(
                reverse("library_import_spotify_playlist"),
                {"source_url": "https://open.spotify.com/playlist/" + "B" * 22},
            )

        self.assertEqual(response.status_code, 302)
        playlist = self.profile.playlists.get(title="Imported Spotify")
        tracks = list(playlist.tracks.all())
        self.assertEqual([track.title for track in tracks], ["First", "Second"])
        self.assertEqual([track.position for track in tracks], [0, 1])
        self.assertEqual(tracks[0].artist, "Artist A, Artist B")
        self.assertEqual(tracks[0].album, "Album")
        self.assertEqual(tracks[0].duration_ms, 123000)
        client.api.assert_called_once_with("playlist_details", "token", playlist_id="B" * 22)
        client.get_playlist_items.assert_called_once_with("token", "B" * 22)

    def test_spotify_playlist_import_rolls_back_empty_or_non_track_response(self):
        client = Mock()
        client.api.return_value = {"name": "Empty"}
        client.get_playlist_items.return_value = [
            {"item": {"type": "episode", "id": "episode-1", "name": "Podcast"}},
            {"item": {"type": "track", "name": "Missing ID"}},
        ]
        before = self.profile.playlists.count()

        with patch("transfer.library_import_views._spotify_access", return_value=(client, "token")):
            response = self.client.post(
                reverse("library_import_spotify_playlist"),
                {"source_url": "https://open.spotify.com/playlist/" + "C" * 22},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.profile.playlists.count(), before)

    def test_soundcloud_import_rejects_host_suffix_trick_before_oauth(self):
        with patch("transfer.library_import_views._soundcloud_access") as access:
            response = self.client.post(
                reverse("library_import_soundcloud_playlist"),
                {"source_url": "https://soundcloud.com.attacker.example/user/playlist"},
            )

        self.assertEqual(response.status_code, 302)
        access.assert_not_called()
        self.assertFalse(self.profile.playlists.exists())

    def test_soundcloud_playlist_import_preserves_track_order_and_artist_fallback(self):
        client = Mock()
        client.resolve.return_value = {"kind": "playlist", "id": 123, "title": "SC playlist"}
        client.playlist_tracks.return_value = [
            {
                "id": 11,
                "title": "First",
                "duration": 125000,
                "user": {"username": "Uploader"},
                "permalink_url": "https://soundcloud.com/uploader/first",
            },
            {
                "id": 12,
                "title": "Second",
                "duration": 95000,
                "metadata_artist": "Original artist",
            },
        ]

        with patch("transfer.library_import_views._soundcloud_access", return_value=(client, "token")):
            response = self.client.post(
                reverse("library_import_soundcloud_playlist"),
                {"source_url": "https://soundcloud.com/uploader/playlist"},
            )

        self.assertEqual(response.status_code, 302)
        playlist = self.profile.playlists.get(title="SC playlist")
        tracks = list(playlist.tracks.all())
        self.assertEqual([track.title for track in tracks], ["First", "Second"])
        self.assertEqual([track.position for track in tracks], [0, 1])
        self.assertEqual(tracks[0].artist, "Uploader")
        self.assertEqual(tracks[1].artist, "Original artist")
        self.assertEqual(tracks[0].duration_ms, 125000)
        client.playlist_tracks.assert_called_once_with("token", 123)

    def test_vk_track_import_rejects_invalid_url_before_provider_request(self):
        with patch("transfer.library_import_views.VKClient") as vk:
            response = self.client.post(
                reverse("library_import_vk_track"),
                {"source_url": "https://attacker.example/audio123"},
            )

        self.assertEqual(response.status_code, 302)
        vk.assert_not_called()
        self.assertFalse(self.profile.playlists.exists())

    def test_vk_track_import_persists_provider_metadata(self):
        track = SimpleNamespace(
            title="VK track",
            artist="VK artist",
            duration=187,
            cover_url="https://cdn.okcdn.ru/cover.jpg",
            audio_id="10_99",
            owner_id=10,
            track_id=99,
        )
        with patch("transfer.library_import_views.VKClient") as vk:
            vk.return_value.fetch_track.return_value = track
            response = self.client.post(
                reverse("library_import_vk_track"),
                {"source_url": "https://vk.ru/audio10_99"},
            )

        self.assertEqual(response.status_code, 302)
        playlist = self.profile.playlists.get(provider=LibraryPlaylist.Provider.VK)
        saved = playlist.tracks.get()
        self.assertEqual(saved.title, "VK track")
        self.assertEqual(saved.artist, "VK artist")
        self.assertEqual(saved.duration_ms, 187000)
        self.assertEqual(saved.external_id, "10_99")
        self.assertEqual(saved.source_provider, LibraryPlaylist.Provider.VK)

    def test_vk_artwork_refresh_rejects_non_vk_playlist_before_api_request(self):
        playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Manual",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        with patch("transfer.library_import_views.VKClient") as vk:
            response = self.client.post(
                reverse("library_refresh_vk_artwork", kwargs={"playlist_id": playlist.pk})
            )

        self.assertEqual(response.status_code, 302)
        vk.assert_not_called()

    def test_vk_artwork_refresh_updates_cover_and_resolved_audio_id(self):
        playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="VK playlist",
            provider=LibraryPlaylist.Provider.VK,
            external_url="https://vk.ru/music/playlist/10_20_key",
        )
        track = LibraryTrack.objects.create(
            playlist=playlist,
            title="Track",
            artist="Artist",
            external_id="10_99",
            source_provider="",
        )
        source = SimpleNamespace(
            owner_id=10,
            track_id=99,
            cover_url="https://cdn.okcdn.ru/new-cover.jpg",
            audio_id="resolved-audio-id",
        )
        with patch("transfer.library_import_views.VKClient") as vk:
            vk.return_value.fetch_playlist.return_value = ("VK playlist", [source])
            response = self.client.post(
                reverse("library_refresh_vk_artwork", kwargs={"playlist_id": playlist.pk})
            )

        self.assertEqual(response.status_code, 302)
        track.refresh_from_db()
        self.assertEqual(track.cover_url, source.cover_url)
        self.assertEqual(track.external_id, "resolved-audio-id")
        self.assertEqual(track.source_provider, LibraryPlaylist.Provider.VK)


class TransferReviewStateMachineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="review-state-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )
        self.source = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Source playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.target = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Target playlist",
            provider=LibraryPlaylist.Provider.SPOTIFY,
        )
        self.first_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="First",
            artist="Artist",
            position=0,
        )
        self.second_track = LibraryTrack.objects.create(
            playlist=self.source,
            title="Second",
            artist="Artist",
            position=1,
        )
        self.review = LibraryTransfer.objects.create(
            profile=self.profile,
            source_playlist=self.source,
            target_provider=LibraryPlaylist.Provider.SPOTIFY,
            provider_playlist_id="",
            target_playlist=self.target,
            total=2,
        )
        self.first_item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.first_track,
            position=0,
            candidates=[{
                "id": "spotify-first",
                "uri": "spotify:track:" + "A" * 22,
                "title": "First candidate",
                "artist": "Artist",
                "url": "https://open.spotify.com/track/" + "A" * 22,
            }],
        )
        self.second_item = LibraryTransferItem.objects.create(
            transfer=self.review,
            source_track=self.second_track,
            position=1,
            candidates=[{
                "id": "spotify-second",
                "uri": "spotify:track:" + "B" * 22,
                "title": "Second candidate",
                "artist": "Artist",
                "url": "https://open.spotify.com/track/" + "B" * 22,
            }],
        )

    def test_cannot_select_later_track_before_earlier_track(self):
        with patch("transfer.library_transfer_review_views._spotify_access") as access:
            response = self.client.post(
                reverse(
                    "select_transfer_candidate",
                    kwargs={"transfer_id": self.review.pk, "item_id": self.second_item.pk},
                ),
                {"candidate_id": "spotify-second"},
            )

        self.assertEqual(response.status_code, 302)
        access.assert_not_called()
        self.second_item.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.second_item.status, LibraryTransferItem.Status.PENDING)
        self.assertEqual(self.review.matched, 0)

    def test_select_candidate_updates_provider_playlist_and_local_mirror(self):
        provider = Mock()
        provider.create_playlist.return_value = "spotify-playlist-id"

        with patch("transfer.library_transfer_review_views._spotify_access", return_value=(provider, "token")):
            response = self.client.post(
                reverse(
                    "select_transfer_candidate",
                    kwargs={"transfer_id": self.review.pk, "item_id": self.first_item.pk},
                ),
                {"candidate_id": "spotify-first"},
            )

        self.assertEqual(response.status_code, 302)
        provider.create_playlist.assert_called_once_with("token", "Source playlist")
        provider.add_items.assert_called_once_with(
            "token",
            "spotify-playlist-id",
            ["spotify:track:" + "A" * 22],
        )
        self.first_item.refresh_from_db()
        self.review.refresh_from_db()
        self.target.refresh_from_db()
        self.assertEqual(self.first_item.status, LibraryTransferItem.Status.MATCHED)
        self.assertEqual(self.first_item.target_external_id, "spotify-first")
        self.assertEqual(self.review.matched, 1)
        self.assertEqual(self.review.provider_playlist_id, "spotify-playlist-id")
        self.assertEqual(self.target.external_url, "https://open.spotify.com/playlist/spotify-playlist-id")
        self.assertEqual(self.target.tracks.get().external_id, "spotify-first")

    def test_provider_failure_does_not_advance_review_state(self):
        provider = Mock()
        provider.create_playlist.side_effect = TransferError("Spotify unavailable")

        with patch("transfer.library_transfer_review_views._spotify_access", return_value=(provider, "token")):
            response = self.client.post(
                reverse(
                    "select_transfer_candidate",
                    kwargs={"transfer_id": self.review.pk, "item_id": self.first_item.pk},
                ),
                {"candidate_id": "spotify-first"},
            )

        self.assertEqual(response.status_code, 302)
        self.first_item.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.first_item.status, LibraryTransferItem.Status.PENDING)
        self.assertEqual(self.review.matched, 0)
        self.assertEqual(self.review.provider_playlist_id, "")

    def test_skipping_items_in_order_completes_review_and_counts_skips(self):
        first_url = reverse(
            "skip_transfer_item",
            kwargs={"transfer_id": self.review.pk, "item_id": self.first_item.pk},
        )
        second_url = reverse(
            "skip_transfer_item",
            kwargs={"transfer_id": self.review.pk, "item_id": self.second_item.pk},
        )

        self.assertEqual(self.client.post(first_url).status_code, 302)
        self.second_item.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.second_item.status, LibraryTransferItem.Status.PENDING)
        self.assertEqual(self.review.status, LibraryTransfer.Status.REVIEW)

        self.assertEqual(self.client.post(second_url).status_code, 302)
        self.first_item.refresh_from_db()
        self.second_item.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.first_item.status, LibraryTransferItem.Status.SKIPPED)
        self.assertEqual(self.second_item.status, LibraryTransferItem.Status.SKIPPED)
        self.assertEqual(self.review.skipped, 2)
        self.assertEqual(self.review.status, LibraryTransfer.Status.COMPLETED)
        self.assertIsNotNone(self.review.completed_at)

    def test_review_cannot_be_accessed_by_another_profile(self):
        other_user = get_user_model().objects.create_user(
            username="review-other-user",
            password=get_random_string(32),
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("transfer_review", kwargs={"transfer_id": self.review.pk})
        )

        self.assertEqual(response.status_code, 404)
