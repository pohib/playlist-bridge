from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils.crypto import get_random_string

from transfer.models import LibraryPlaylist, LibraryProfile, LibraryTrack
from transfer.services.library_management import (
    LibraryManagementError,
    add_track,
    create_playlist,
    merge_playlists,
    update_profile,
    upload_local_track,
)


class LibraryManagementServiceTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="library-management-service",
            password=get_random_string(32),
        )
        self.profile = LibraryProfile.objects.create(
            user=user, session_fingerprint="a" * 64
        )
        self.first = LibraryPlaylist.objects.create(
            profile=self.profile, title="First",
            provider=LibraryPlaylist.Provider.VK,
        )
        self.second = LibraryPlaylist.objects.create(
            profile=self.profile, title="Second",
            provider=LibraryPlaylist.Provider.SPOTIFY,
        )

    def test_create_playlist_normalizes_and_persists_fields(self):
        playlist = create_playlist(
            self.profile,
            title="  Collection  ",
            provider=LibraryPlaylist.Provider.MANUAL,
            description="  Description ",
            external_url="https://example.com/list",
        )
        self.assertEqual(playlist.title, "Collection")
        self.assertEqual(playlist.description, "Description")
        self.assertEqual(playlist.external_url, "https://example.com/list")

    def test_create_playlist_rejects_unsafe_external_url(self):
        with self.assertRaises(LibraryManagementError):
            create_playlist(
                self.profile, title="Unsafe",
                provider=LibraryPlaylist.Provider.MANUAL,
                external_url="javascript:alert(1)",
            )
        self.assertFalse(self.profile.playlists.filter(title="Unsafe").exists())

    def test_add_track_appends_and_converts_duration(self):
        track = add_track(
            self.first, title="  Track ", artist=" Artist ",
            duration_seconds="123.5",
        )
        self.assertEqual(track.title, "Track")
        self.assertEqual(track.artist, "Artist")
        self.assertEqual(track.duration_ms, 123500)
        self.assertEqual(track.position, 0)

    def test_add_track_rejects_invalid_duration_without_write(self):
        with self.assertRaises(LibraryManagementError):
            add_track(
                self.first, title="Track", artist="Artist",
                duration_seconds="-1",
            )
        self.assertFalse(self.first.tracks.exists())

    def test_merge_preserves_source_order_and_deduplicates(self):
        LibraryTrack.objects.create(
            playlist=self.first, title="Song", artist="Artist", position=0
        )
        LibraryTrack.objects.create(
            playlist=self.second, title=" song ", artist="ARTIST", position=0
        )
        LibraryTrack.objects.create(
            playlist=self.second, title="Another", artist="Artist", position=1
        )
        merged, count = merge_playlists(
            self.profile, [self.first.pk, self.second.pk], "Merged"
        )
        self.assertEqual(count, 2)
        self.assertEqual(
            list(merged.tracks.order_by("position").values_list("title", flat=True)),
            ["Song", "Another"],
        )

    def test_merge_rejects_foreign_playlist_without_creating_collection(self):
        other = LibraryProfile.objects.create(session_fingerprint="b" * 64)
        foreign = LibraryPlaylist.objects.create(profile=other, title="Private")
        before = self.profile.playlists.count()
        with self.assertRaises(LibraryManagementError):
            merge_playlists(
                self.profile, [self.first.pk, foreign.pk], "Injected"
            )
        self.assertEqual(self.profile.playlists.count(), before)

    def test_merge_empty_sources_rolls_back_collection(self):
        before = self.profile.playlists.count()
        with self.assertRaises(LibraryManagementError):
            merge_playlists(
                self.profile, [self.first.pk, self.second.pk], "Empty"
            )
        self.assertEqual(self.profile.playlists.count(), before)

    def test_local_upload_rejects_mismatched_signature(self):
        upload = SimpleUploadedFile(
            "not-audio.mp3", b"<html>not audio</html>",
            content_type="audio/mpeg",
        )
        before = LibraryTrack.objects.count()
        with self.assertRaises(LibraryManagementError):
            upload_local_track(
                self.profile, title="Spoof", artist="Attacker", uploaded=upload
            )
        self.assertEqual(LibraryTrack.objects.count(), before)

    def test_profile_name_validation_and_persistence(self):
        update_profile(self.profile, "  Listener ")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.display_name, "Listener")
        with self.assertRaises(LibraryManagementError):
            update_profile(self.profile, " ")


class LibraryManagementBoundaryTests(TestCase):
    def test_http_adapter_does_not_own_domain_persistence(self):
        from pathlib import Path
        source = Path("transfer/library_management_views.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("LibraryTrack.objects.create", source)
        self.assertNotIn("LibraryPlaylist.objects.create", source)
        self.assertIn("services.library_management", source)
