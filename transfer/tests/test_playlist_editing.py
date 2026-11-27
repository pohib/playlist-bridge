from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from transfer.credentials import get_session_fingerprint
from transfer.models import LibraryPlaylist, LibraryProfile, LibraryTrack
from transfer.services.common import parse_vk_track_reference, parse_vk_track_url
from transfer.services.vk_client import VKClient


class VKTrackURLTests(TestCase):
    def test_parser_accepts_vk_ru_audio_link_with_access_key(self):
        url = "https://vk.ru/audio241688629_456241110_5a0719ae5957d76bcb"
        self.assertEqual(
            parse_vk_track_reference(url),
            (241688629, 456241110, "5a0719ae5957d76bcb"),
        )
        self.assertEqual(parse_vk_track_url(url), (241688629, 456241110))

    def test_parser_rejects_untrusted_host_even_with_valid_audio_path(self):
        with self.assertRaises(ValueError):
            parse_vk_track_reference(
                "https://vk.ru.attacker.example/audio241688629_456241110_key"
            )

    def test_vk_client_passes_access_key_to_audio_get_by_id(self):
        client = VKClient()
        client.post = Mock(return_value={
            "response": [{
                "owner_id": 241688629,
                "id": 456241110,
                "artist": "Artist",
                "title": "Track",
                "duration": 120,
            }]
        })

        track = client.fetch_track(
            "https://vk.ru/audio241688629_456241110_5a0719ae5957d76bcb"
        )

        client.post.assert_called_once_with(
            "audio.getById",
            data={"audios": "241688629_456241110_5a0719ae5957d76bcb"},
        )
        self.assertEqual(
            track.audio_id,
            "241688629_456241110_5a0719ae5957d76bcb",
        )


class VKClientPlaylistMetadataAndPlaybackTests(TestCase):
    def test_playlist_import_uses_vk_playlist_title(self):
        client = VKClient()
        client.post = Mock(side_effect=[
            {"response": {"audios": [{"audio_id": "241688629_456241110_access"}]}},
            {"response": [{
                "owner_id": 241688629, "id": 456241110,
                "artist": "Artist", "title": "Track", "duration": 120,
            }]},
            {"response": {"title": "My VK playlist"}},
        ])

        title, tracks = client.fetch_playlist(
            "https://vk.ru/music/playlist/241688629_40_941bcddb919ded249e"
        )

        self.assertEqual(title, "My VK playlist")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(client.post.call_args_list[-1].args[0], "audio.getPlaylistById")
        self.assertEqual(client.post.call_args_list[-1].kwargs["data"], {
            "owner_id": 241688629, "playlist_id": 40,
            "extended": 1, "access_key": "941bcddb919ded249e",
        })

    def test_vk_client_uses_legacy_direct_mp3_url_when_stream_list_is_missing(self):
        client = VKClient()
        client.post = Mock(return_value={"response": [{
            "owner_id": 241688629, "id": 456241110,
            "url": "https://cs1.userapi.com/audio.mp3",
        }]})

        result = client.get_track_stream("241688629_456241110", "mp3")

        self.assertEqual(result, {
            "url": "https://cs1.userapi.com/audio.mp3", "format": "mp3",
        })

    def test_vk_client_rejects_untrusted_legacy_mp3_url(self):
        client = VKClient()
        client.post = Mock(return_value={"response": [{
            "owner_id": 241688629, "id": 456241110,
            "url": "https://attacker.example/audio.mp3",
        }]})

        with self.assertRaisesRegex(Exception, "небезопасный адрес"):
            client.get_track_stream("241688629_456241110", "mp3")

class PlaylistEditingWorkflowTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="playlist-editing-user",
            password=get_random_string(32),
        )
        self.client.force_login(user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="Before",
            description="Old description",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        self.first = LibraryTrack.objects.create(
            playlist=self.playlist, title="First", artist="Artist", position=0,
        )
        self.second = LibraryTrack.objects.create(
            playlist=self.playlist, title="Second", artist="Artist", position=1,
        )

    def test_playlist_metadata_can_be_edited(self):
        response = self.client.post(
            reverse("library_update_playlist", kwargs={"playlist_id": self.playlist.pk}),
            {"title": "  Updated  ", "description": "  New description  "},
        )
        self.assertEqual(response.status_code, 302)
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.title, "Updated")
        self.assertEqual(self.playlist.description, "New description")

    def test_track_order_can_be_changed(self):
        response = self.client.post(
            reverse(
                "library_move_track",
                kwargs={"playlist_id": self.playlist.pk, "track_id": self.second.pk},
            ),
            {"direction": "up"},
        )
        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.position, 1)
        self.assertEqual(self.second.position, 0)

    def test_track_cannot_be_moved_into_another_owned_playlist(self):
        other = LibraryPlaylist.objects.create(
            profile=self.profile, title="Other",
            provider=LibraryPlaylist.Provider.MANUAL,
        )
        response = self.client.post(
            reverse(
                "library_move_track",
                kwargs={"playlist_id": other.pk, "track_id": self.first.pk},
            ),
            {"direction": "down"},
        )
        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.assertEqual(self.first.position, 0)

    def test_foreign_playlist_cannot_be_edited(self):
        other_profile = LibraryProfile.objects.create(
            session_fingerprint="f" * 64,
        )
        foreign = LibraryPlaylist.objects.create(profile=other_profile, title="Private")
        response = self.client.post(
            reverse("library_update_playlist", kwargs={"playlist_id": foreign.pk}),
            {"title": "Changed", "description": ""},
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.title, "Private")

    def test_single_vk_track_can_be_added_to_existing_playlist(self):
        track = type("VKTrackStub", (), {
            "title": "Imported VK track",
            "artist": "VK artist",
            "duration": 175,
            "cover_url": "https://cdn.okcdn.ru/cover.jpg",
            "audio_id": "241688629_456241110_5a0719ae5957d76bcb",
            "owner_id": 241688629,
            "track_id": 456241110,
        })()
        with patch("transfer.library_vk_import_views.VKClient") as vk:
            vk.return_value.fetch_track.return_value = track
            response = self.client.post(
                reverse("library_import_vk_track"),
                {
                    "source_url": "https://vk.ru/audio241688629_456241110_5a0719ae5957d76bcb",
                    "playlist_id": str(self.playlist.pk),
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.profile.playlists.count(), 1)
        added = self.playlist.tracks.get(title="Imported VK track")
        self.assertEqual(added.position, 2)
        self.assertEqual(added.source_provider, LibraryPlaylist.Provider.VK)
        self.assertEqual(
            added.external_id,
            "241688629_456241110_5a0719ae5957d76bcb",
        )

    def test_single_vk_track_cannot_be_added_to_foreign_playlist(self):
        other_profile = LibraryProfile.objects.create(
            session_fingerprint="e" * 64,
        )
        foreign = LibraryPlaylist.objects.create(profile=other_profile, title="Private")
        with patch("transfer.library_vk_import_views.VKClient") as vk:
            response = self.client.post(
                reverse("library_import_vk_track"),
                {
                    "source_url": "https://vk.ru/audio241688629_456241110_key",
                    "playlist_id": str(foreign.pk),
                },
            )
        self.assertEqual(response.status_code, 404)
        vk.assert_not_called()


    def test_single_spotify_track_can_be_added_to_existing_playlist(self):
        track = {
            "id": "A" * 22,
            "name": "Spotify imported",
            "artists": [{"name": "Spotify artist"}],
            "album": {"name": "Album", "images": []},
            "duration_ms": 180000,
            "external_urls": {"spotify": "https://open.spotify.com/track/" + "A" * 22},
        }
        client = Mock()
        client.track_details.return_value = track
        with patch("transfer.library_spotify_import_views._spotify_access", return_value=(client, "token")):
            response = self.client.post(
                reverse("library_import_spotify_track"),
                {
                    "source_url": "https://open.spotify.com/track/" + "A" * 22,
                    "playlist_id": str(self.playlist.pk),
                },
            )
        self.assertEqual(response.status_code, 302)
        added = self.playlist.tracks.get(title="Spotify imported")
        self.assertEqual(added.position, 2)
        self.assertEqual(added.source_provider, LibraryPlaylist.Provider.SPOTIFY)

    def test_single_soundcloud_track_can_be_added_to_existing_playlist(self):
        client = Mock()
        client.resolve.return_value = {
            "kind": "track",
            "id": 12345,
            "title": "SoundCloud imported",
            "metadata_artist": "SC artist",
            "duration": 195000,
            "permalink_url": "https://soundcloud.com/artist/track",
            "user": {"username": "Uploader"},
        }
        with patch("transfer.library_soundcloud_import_views._soundcloud_access", return_value=(client, "token")):
            response = self.client.post(
                reverse("library_import_soundcloud_track"),
                {
                    "source_url": "https://soundcloud.com/artist/track",
                    "playlist_id": str(self.playlist.pk),
                },
            )
        self.assertEqual(response.status_code, 302)
        added = self.playlist.tracks.get(title="SoundCloud imported")
        self.assertEqual(added.position, 2)
        self.assertEqual(added.source_provider, LibraryPlaylist.Provider.SOUNDCLOUD)


    def test_track_metadata_can_be_edited(self):
        response = self.client.post(
            reverse(
                "library_update_track",
                kwargs={"playlist_id": self.playlist.pk, "track_id": self.first.pk},
            ),
            {"title": "  Edited title ", "artist": " New artist ", "album": " New album "},
        )
        self.assertEqual(response.status_code, 302)
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, "Edited title")
        self.assertEqual(self.first.artist, "New artist")
        self.assertEqual(self.first.album, "New album")

    def test_track_metadata_edit_rejects_foreign_playlist(self):
        other_profile = LibraryProfile.objects.create(
            session_fingerprint="c" * 64,
        )
        foreign = LibraryPlaylist.objects.create(profile=other_profile, title="Private")
        response = self.client.post(
            reverse(
                "library_update_track",
                kwargs={"playlist_id": foreign.pk, "track_id": self.first.pk},
            ),
            {"title": "Injected", "artist": "Attacker"},
        )
        self.assertEqual(response.status_code, 404)
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, "First")
