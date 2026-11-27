from unittest.mock import Mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ..models import LibraryPlaylist, LibraryProfile, LibraryTrack
from ..services.common import TransferError
from ..services.library_soundcloud_upload import upload_soundcloud_track


class SoundCloudUploadServiceTests(TestCase):
    def setUp(self):
        self.profile = LibraryProfile.objects.create(session_fingerprint="a" * 64)
        self.client = Mock()
        self.client.upload_track.return_value = {
            "id": 12345,
            "permalink_url": "https://soundcloud.com/artist/uploaded-track",
            "duration": 125000,
        }
        self.access = Mock(return_value=(self.client, "access-token"))

    def _upload(self, **overrides):
        values = {
            "profile_provider": lambda: self.profile,
            "uploaded": SimpleUploadedFile(
                "track.mp3",
                b"ID3" + b"\x00" * 20,
                content_type="audio/mpeg",
            ),
            "title": "Uploaded track",
            "artist": "Artist",
            "description": "Description",
            "soundcloud_access": self.access,
        }
        values.update(overrides)
        return upload_soundcloud_track(**values)

    def test_upload_persists_provider_result_as_one_library_playlist(self):
        playlist = self._upload()

        self.assertEqual(playlist.profile, self.profile)
        self.assertEqual(playlist.provider, LibraryPlaylist.Provider.SOUNDCLOUD)
        self.assertEqual(playlist.title, "Uploaded track")
        self.assertEqual(playlist.external_url, "https://soundcloud.com/artist/uploaded-track")
        track = playlist.tracks.get()
        self.assertEqual(track.title, "Uploaded track")
        self.assertEqual(track.artist, "Artist")
        self.assertEqual(track.external_id, "12345")
        self.assertEqual(track.duration_ms, 125000)
        self.assertEqual(track.position, 0)
        self.client.upload_track.assert_called_once_with(
            "access-token",
            self.client.upload_track.call_args.args[1],
            "Uploaded track",
            "Artist",
            "Description",
        )

    def test_invalid_audio_is_rejected_before_provider_authorization(self):
        before = LibraryPlaylist.objects.count()
        upload = SimpleUploadedFile("payload.mp3", b"<html>not audio</html>")

        with self.assertRaises(TransferError):
            self._upload(uploaded=upload)

        self.access.assert_not_called()
        self.assertEqual(LibraryPlaylist.objects.count(), before)

    def test_unsupported_extension_is_rejected_before_provider_authorization(self):
        before = LibraryPlaylist.objects.count()
        upload = SimpleUploadedFile("payload.exe", b"ID3" + b"\x00" * 20)

        with self.assertRaises(TransferError):
            self._upload(uploaded=upload)

        self.access.assert_not_called()
        self.assertEqual(LibraryPlaylist.objects.count(), before)

    def test_provider_failure_does_not_create_local_records(self):
        self.client.upload_track.side_effect = TransferError("SoundCloud unavailable")
        before_playlists = LibraryPlaylist.objects.count()
        before_tracks = LibraryTrack.objects.count()

        with self.assertRaisesMessage(TransferError, "SoundCloud unavailable"):
            self._upload()

        self.assertEqual(LibraryPlaylist.objects.count(), before_playlists)
        self.assertEqual(LibraryTrack.objects.count(), before_tracks)
        self.assertFalse(self.profile.playlists.exists())

    def test_missing_provider_track_id_does_not_create_local_records(self):
        self.client.upload_track.return_value = {
            "permalink_url": "https://soundcloud.com/artist/uploaded-track",
        }
        before = LibraryPlaylist.objects.count()

        with self.assertRaisesMessage(TransferError, "не вернул идентификатор"):
            self._upload()

        self.assertEqual(LibraryPlaylist.objects.count(), before)

    def test_malformed_provider_duration_falls_back_to_zero(self):
        self.client.upload_track.return_value["duration"] = "unknown"

        playlist = self._upload()

        self.assertEqual(playlist.tracks.get().duration_ms, 0)

    def test_profile_is_resolved_only_after_provider_upload_succeeds(self):
        profile_provider = Mock(return_value=self.profile)
        self.client.upload_track.side_effect = TransferError("temporary error")

        with self.assertRaises(TransferError):
            self._upload(profile_provider=profile_provider)

        profile_provider.assert_not_called()
