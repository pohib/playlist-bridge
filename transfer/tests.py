# ruff: noqa: I001
import base64
import hashlib
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.crypto import get_random_string
from requests import HTTPError

from .core import (
    ReauthorizationRequired,
    SoundCloudClient,
    SpotifyClient,
    TransferError,
    VKClient,
    VKIDClient,
    VKTrack,
    normalize_track_text,
    parse_vk_playlist_url,
    parse_vk_track_url,
)
from .credentials import decrypt_payload, get_access_token, get_session_fingerprint, store_credential
from .models import OAuthCredential, TransferJob


TEST_PASSWORD = get_random_string(32)


class InputValidationTests(TestCase):
    def test_vk_playlist_url_parsed(self):
        self.assertEqual(
            parse_vk_playlist_url("https://vk.ru/music/playlist/241688629_5_abcd"),
            (241688629, 5, "abcd"),
        )

    def test_foreign_host_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("https://evil.example/music/playlist/1_2_key")

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            parse_vk_playlist_url("javascript:alert(1)")

    def test_normalization(self):
        self.assertEqual(normalize_track_text("Ёлка — Прованс!"), "елка прованс")


class SpotifyApiDestinationTests(TestCase):
    def setUp(self):
        self.client = SpotifyClient("client-id", "client-secret", "https://example.test/callback/")

    def test_spotify_api_destinations_are_fixed_operations(self):
        self.assertEqual(
            self.client._api_destination("search"),
            ("GET", "https://api.spotify.com/v1/search"),
        )
        playlist_id = "AbCdEf1234567890GhIjKl"
        self.assertEqual(
            self.client._api_destination("playlist_items", playlist_id),
            ("POST", f"https://api.spotify.com/v1/playlists/{playlist_id}/items"),
        )

    def test_spotify_manual_search_uses_general_track_query(self):
        client = SpotifyClient("client-id", "client-secret", "https://example.test/callback/")
        client.api = Mock(return_value={"tracks": {"items": []}})
        self.assertEqual(client.search_tracks("token", "Artist - Track"), [])
        client.api.assert_called_once_with(
            "search",
            "token",
            params={"q": "Artist - Track", "type": "track", "limit": 10},
        )

    def test_spotify_add_items_supports_original_position(self):
        client = SpotifyClient("client-id", "client-secret", "https://example.test/callback/")
        client.api = Mock()
        client.add_items("token", "AbCdEf1234567890GhIjKl", ["spotify:track:4iV5W9uYEdYUVa79Axb7Rh"], position=3)
        client.api.assert_called_once_with(
            "playlist_items",
            "token",
            playlist_id="AbCdEf1234567890GhIjKl",
            body={"uris": ["spotify:track:4iV5W9uYEdYUVa79Axb7Rh"], "position": 3},
        )

    def test_spotify_api_rejects_unknown_operations_and_untrusted_ids(self):
        for operation in ("https://attacker.example/steal", "//attacker.example", "admin"):
            with self.subTest(operation=operation), self.assertRaises(TransferError):
                self.client._api_destination(operation)
        for playlist_id in (
            "../../admin",
            "//attacker.example",
            "short",
            "A" * 23,
            "A" * 21 + "/",
            None,
        ):
            with self.subTest(playlist_id=playlist_id), self.assertRaises(TransferError):
                self.client._api_destination("playlist_details", playlist_id)

    def test_spotify_api_does_not_follow_redirects(self):
        response = Mock()
        response.status_code = 302
        self.client.http.request = Mock(return_value=response)
        with self.assertRaises(TransferError):
            self.client.api("current_user", "test-token")
        self.client.http.request.assert_called_once()
        self.assertIs(self.client.http.request.call_args.kwargs["allow_redirects"], False)


class VKPlaylistBatchTests(TestCase):
    def test_fetch_playlist_reads_audio_get_items_and_preserves_order(self):
        client = VKClient("test-access", "5.289", "vk-app")
        audio_items = [
            {
                "owner_id": 42,
                "id": index,
                "artist": "Artist",
                "title": f"Track {index}",
                "duration": 180,
            }
            for index in range(1, 46)
        ]
        metadata = {"response": {"title": "Test playlist"}}
        audio_response = {"response": {"count": 45, "items": audio_items}}

        with patch.object(client, "post", side_effect=[metadata, audio_response]) as post:
            name, tracks = client.fetch_playlist(
                "https://vk.ru/music/playlist/42_9_testkey"
            )

        self.assertEqual(name, "Test playlist")
        self.assertEqual(len(tracks), 45)
        self.assertEqual([track.track_id for track in tracks], list(range(1, 46)))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[1].kwargs["data"],
            {
                "owner_id": 42,
                "album_id": 9,
                "count": 1000,
                "offset": 0,
                "access_key": "testkey",
            },
        )

    def test_fetch_playlist_accepts_list_response_shape(self):
        client = VKClient("test-access", "5.289", "vk-app")
        with patch.object(
            client,
            "post",
            side_effect=[
                {"response": {"title": "List shape"}},
                {"response": [
                    {"owner_id": 42, "id": 7, "artist": "Artist", "title": "Track", "duration": 120}
                ]},
            ],
        ):
            name, tracks = client.fetch_playlist("https://vk.ru/music/playlist/42_9")
        self.assertEqual(name, "List shape")
        self.assertEqual([track.track_id for track in tracks], [7])

    def test_fetch_playlist_rejects_empty_playlist(self):
        client = VKClient("test-access", "5.289", "vk-app")
        with patch.object(
            client,
            "post",
            side_effect=[
                {"response": {"title": "Empty"}},
                {"response": {"count": 0, "items": []}},
            ],
        ), self.assertRaises(TransferError):
            client.fetch_playlist("https://vk.ru/music/playlist/42_9")


class HttpSurfaceTests(TestCase):
    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_home(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("Permissions-Policy", response.headers)
        self.assertEqual(response.headers["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")

    def test_health(self):
        self.assertEqual(self.client.get(reverse("healthz")).json(), {"status": "ok"})

    def test_transfer_requires_post(self):
        self.assertEqual(self.client.get(reverse("transfer_playlist")).status_code, 405)


class VersionedApiTests(TestCase):
    def test_openapi_document(self):
        response = self.client.get(reverse("api_openapi"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["openapi"], "3.1.0")

    def test_api_status_contract(self):
        response = self.client.get(reverse("api_status"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spotify_connected", response.json())
        self.assertIn("vk_connected", response.json())
        self.assertEqual(response.json()["api_version"], "1")

    def test_create_transfer_requires_json(self):
        response = self.client.post(reverse("api_create_transfer"), {"source_url": "https://vk.ru/"})
        self.assertEqual(response.status_code, 415)

    def test_create_transfer_rejects_invalid_playlist_url(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data='{"source_url":"https://attacker.example/music/playlist/1_2"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(
        VK_ID_CLIENT_ID="test-vk-app",
        SPOTIFY_CLIENT_ID="test-client",
        SPOTIFY_CLIENT_SECRET=Fernet.generate_key().decode(),
        TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    def test_create_transfer_requires_spotify_session(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data='{"source_url":"https://vk.ru/music/playlist/241688629_5"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Сначала подключи Spotify.")



class OAuthSecurityTests(TestCase):
    def test_vk_oauth_authorization_uses_pkce_s256(self):
        client = VKIDClient("vk-app-id", "https://example.test/vk/callback/")
        verifier = "a" * 64
        url = client.authorization_url("random-state", verifier)
        params = parse_qs(urlparse(url).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"][0], expected)
        self.assertEqual(params["code_challenge_method"][0], "s256")
        self.assertEqual(params["state"][0], "random-state")
        self.assertEqual(params["scope"][0], "audio")

    def test_vk_oauth_secrets_are_sent_in_post_body(self):
        service_token = Fernet.generate_key().decode()
        client = VKIDClient("vk-app-id", "https://example.test/vk/callback/", service_token)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "access_token": Fernet.generate_key().decode(),
            "refresh_token": Fernet.generate_key().decode(),
            "state": "expected-state",
        }
        client.http.post = Mock(return_value=response)

        client.exchange_code("one-time-code", "device-id", "expected-state", "pkce-verifier")

        call = client.http.post.call_args
        self.assertNotIn("params", call.kwargs)
        self.assertEqual(call.kwargs["data"]["code"], "one-time-code")
        self.assertEqual(call.kwargs["data"]["code_verifier"], "pkce-verifier")
        self.assertEqual(call.kwargs["data"]["service_token"], service_token)
        self.assertEqual(call.kwargs["data"]["state"], "expected-state")

    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_oauth_tokens_are_encrypted_at_rest(self):
        access_token = Fernet.generate_key().decode()
        refresh_token = Fernet.generate_key().decode()
        token = {"access_token": access_token, "refresh_token": refresh_token}
        credential = store_credential("a" * 64, "spotify", token, "spotify-user")
        self.assertNotIn(access_token, credential.encrypted_payload)
        self.assertNotIn(refresh_token, credential.encrypted_payload)
        self.assertEqual(decrypt_payload(credential.encrypted_payload)["access_token"], access_token)
        self.assertEqual(OAuthCredential.objects.count(), 1)

    def test_provider_disconnect_requires_post(self):
        self.assertEqual(self.client.get(reverse("disconnect_spotify")).status_code, 405)
        self.assertEqual(self.client.get(reverse("disconnect_vk")).status_code, 405)



class SessionIsolationTests(TestCase):
    @staticmethod
    def fingerprint(client):
        session = SessionStore()
        session.create()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return get_session_fingerprint(client)

    def test_user_cannot_read_another_sessions_transfer_or_report(self):
        owner = self.client
        attacker = self.client_class()
        owner_fingerprint = self.fingerprint(owner)
        self.fingerprint(attacker)

        job = TransferJob.objects.create(
            session_fingerprint=owner_fingerprint,
            source_url="https://vk.ru/music/playlist/241688629_5",
            status=TransferJob.Status.SUCCEEDED,
            result={"report": [{"title": "private track"}]},
        )

        own_response = owner.get(reverse("api_transfer_detail", kwargs={"job_id": job.pk}))
        self.assertEqual(own_response.status_code, 200)

        foreign_detail = attacker.get(reverse("api_transfer_detail", kwargs={"job_id": job.pk}))
        foreign_report = attacker.get(reverse("api_transfer_report", kwargs={"job_id": job.pk}))
        self.assertEqual(foreign_detail.status_code, 404)
        self.assertEqual(foreign_report.status_code, 404)
        self.assertNotIn(b"private track", foreign_report.content)


class TransferConcurrencyTests(TestCase):
    def setUp(self):
        self.fingerprint = "f" * 64

    def create_job(self):
        return TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.ru/music/playlist/241688629_5",
        )

    def test_database_rejects_second_active_job_for_same_session(self):
        self.create_job()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_job()

    @patch("transfer.tasks.get_access_token", return_value=("test-token", {}))
    @patch("transfer.tasks.execute_transfer")
    def test_duplicate_celery_delivery_executes_transfer_once(self, execute, _get_token):
        from .tasks import run_transfer

        job = self.create_job()
        execute.return_value = {
            "total": 1,
            "matched": 1,
            "not_found": 0,
            "ambiguous": 0,
            "report": [],
            "target_playlist_id": "spotify-playlist-id",
        }

        run_transfer(str(job.pk))
        run_transfer(str(job.pk))

        self.assertEqual(execute.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, TransferJob.Status.SUCCEEDED)


class OAuthCallbackNegativeTests(TestCase):
    @patch("transfer.views.SpotifyClient.exchange_code")
    def test_spotify_callback_rejects_missing_or_invalid_state(self, exchange_code):
        response = self.client.get(
            reverse("spotify_callback"),
            {"code": "attacker-controlled-code", "state": "wrong-state"},
        )
        self.assertEqual(response.status_code, 302)
        exchange_code.assert_not_called()


class ApiInputNegativeTests(TestCase):
    def test_malformed_json_is_rejected(self):
        response = self.client.post(
            reverse("api_create_transfer"),
            data="{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())



class ApiSessionSecurityTests(TestCase):
    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_api_requires_csrf_for_cookie_authenticated_post(self):
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post(
            reverse("api_create_transfer"),
            data='{"source_url":"https://vk.ru/music/playlist/241688629_5"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    @patch("transfer.tasks.run_transfer.delay")
    def test_repeated_transfer_request_reuses_active_job(self, enqueue):
        session = SessionStore()
        session.create()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        fingerprint = get_session_fingerprint(self.client)
        store_credential(fingerprint, "spotify", {"access_token": Fernet.generate_key().decode()})
        store_credential(fingerprint, "vk", {"access_token": Fernet.generate_key().decode()})

        payload = '{"source_url":"https://vk.ru/music/playlist/241688629_5"}'
        first = self.client.post(
            reverse("api_create_transfer"), data=payload, content_type="application/json"
        )
        second = self.client.post(
            reverse("api_create_transfer"), data=payload, content_type="application/json"
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["job"]["id"], second.json()["job"]["id"])
        self.assertEqual(TransferJob.objects.filter(session_fingerprint=fingerprint).count(), 1)
        enqueue.assert_called_once()



class SpotifyRefreshLifecycleTests(TestCase):
    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_six_month_old_spotify_authorization_is_deleted(self):
        fingerprint = "s" * 64
        store_credential(
            fingerprint,
            "spotify",
            {
                "access_token": Fernet.generate_key().decode(),
                "refresh_token": Fernet.generate_key().decode(),
                "obtained_at": time.time() - 3600,
                "authorized_at": time.time() - 181 * 24 * 60 * 60,
            },
        )

        with self.assertRaises(ReauthorizationRequired):
            get_access_token(fingerprint, "spotify", Mock())

        self.assertFalse(OAuthCredential.objects.filter(
            session_fingerprint=fingerprint, provider="spotify"
        ).exists())

    def test_spotify_invalid_grant_requires_reauthorization(self):
        client = SpotifyClient("client-id", Fernet.generate_key().decode(), "https://example.test/callback/")
        response = Mock()
        response.raise_for_status.side_effect = HTTPError("invalid_grant")
        response.json.return_value = {"error": "invalid_grant"}
        client.http.post = Mock(return_value=response)

        with self.assertRaises(ReauthorizationRequired):
            client.refresh_token(Fernet.generate_key().decode())



class LibraryWorkspaceTests(TestCase):
    def test_create_playlist_and_add_track(self):
        response = self.client.post(
            reverse("library_create_playlist"),
            {
                "title": "Night Drive",
                "provider": "vk",
                "description": "Late night set",
                "external_url": "https://vk.com/music",
            },
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryPlaylist, LibraryProfile, LibraryTrack
        playlist = LibraryPlaylist.objects.get(title="Night Drive")
        self.assertEqual(playlist.provider, "vk")

        response = self.client.post(
            reverse("library_add_track", kwargs={"playlist_id": playlist.pk}),
            {
                "title": "After Hours",
                "artist": "The Weeknd",
                "album": "After Hours",
                "duration_seconds": "240",
            },
        )
        self.assertEqual(response.status_code, 302)
        track = LibraryTrack.objects.get(playlist=playlist)
        self.assertEqual(track.duration_ms, 240000)
        self.assertEqual(track.artist, "The Weeknd")
        self.assertEqual(LibraryProfile.objects.count(), 1)

    def test_library_objects_are_isolated_between_sessions(self):
        from .models import LibraryPlaylist, LibraryProfile
        self.client.post(
            reverse("library_create_playlist"),
            {"title": "Private list", "provider": "manual"},
        )
        playlist = LibraryPlaylist.objects.get(title="Private list")

        other_client = self.client_class()
        response = other_client.post(
            reverse("library_add_track", kwargs={"playlist_id": playlist.pk}),
            {"title": "Hidden", "artist": "Other"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(playlist.tracks.count(), 0)
        self.assertEqual(LibraryProfile.objects.count(), 2)

    def test_playlist_rejects_non_http_external_url(self):
        response = self.client.post(
            reverse("library_create_playlist"),
            {"title": "Bad link", "provider": "manual", "external_url": "javascript:alert(1)"},
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryPlaylist
        self.assertFalse(LibraryPlaylist.objects.filter(title="Bad link").exists())

    def test_profile_name_can_be_updated(self):
        response = self.client.post(
            reverse("library_update_profile"),
            {"display_name": "My Music"},
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryProfile
        self.assertEqual(LibraryProfile.objects.get().display_name, "My Music")


class VKLibraryImportTests(TestCase):
    @patch("transfer.library_views.get_access_token", return_value=("vk-access", {}))
    @patch("transfer.core.VKClient.fetch_playlist", return_value=(
        "VK imported playlist",
        [
            VKTrack(10, 101, "Artist A", "Track A", 185),
            VKTrack(10, 102, "Artist B", "Track B", 210),
        ],
    ))
    @patch("transfer.library_views.VKIDClient")
    @override_settings(VK_ID_CLIENT_ID="vk-client", VK_API_VERSION="5.289")
    def test_import_saves_playlist_tracks_in_original_order(
        self, oauth_client, fetch_playlist, _get_access_token
    ):
        oauth_client.return_value = Mock()
        response = self.client.post(
            reverse("library_import_vk"),
            {"source_url": "https://vk.ru/music/playlist/10_5_key"},
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryPlaylist
        playlist = LibraryPlaylist.objects.get(title="VK imported playlist")
        tracks = list(playlist.tracks.all())
        self.assertEqual([track.title for track in tracks], ["Track A", "Track B"])
        self.assertEqual([track.position for track in tracks], [0, 1])
        self.assertEqual([track.external_id for track in tracks], ["10_101", "10_102"])
        self.assertEqual([track.duration_ms for track in tracks], [185000, 210000])
        fetch_playlist.assert_called_once()

    def test_import_rejects_invalid_vk_url_before_oauth(self):
        with patch("transfer.credentials.get_access_token") as get_token:
            response = self.client.post(
                reverse("library_import_vk"),
                {"source_url": "https://attacker.example/music/playlist/10_5"},
            )
        self.assertEqual(response.status_code, 302)
        get_token.assert_not_called()

    def test_source_redirect_rejects_unsafe_stored_url(self):
        from .credentials import get_session_fingerprint
        from .models import LibraryPlaylist, LibraryProfile
        profile, _ = LibraryProfile.objects.get_or_create(
            session_fingerprint=get_session_fingerprint(self.client),
        )
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title="Unsafe legacy link",
            provider="manual",
            external_url="javascript:alert(1)",
        )
        response = self.client.get(
            reverse("library_open_playlist_source", kwargs={"playlist_id": playlist.pk}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("library"))


class SoundCloudIntegrationTests(TestCase):
    def test_soundcloud_playlist_update_replaces_tracks_with_validated_ids(self):
        client = SoundCloudClient("client-id", "client-secret", "https://example.test/callback/")
        client._request = Mock(return_value={})
        client.update_playlist_tracks("token", "555", ["987", "988"])
        client._request.assert_called_once_with(
            "PUT",
            "/playlists/555",
            "token",
            json_body={"playlist": {"tracks": [{"id": 987}, {"id": 988}]}},
        )
        with self.assertRaises(TransferError):
            client.update_playlist_tracks("token", "bad-id", ["987"])
        with self.assertRaises(TransferError):
            client.update_playlist_tracks("token", "555", ["https://evil.example/track"])


    def test_soundcloud_authorization_uses_pkce_s256(self):
        client = SoundCloudClient("client-id", "client-secret", "https://example.test/soundcloud/callback/")
        url = client.authorization_url("state-value", "a-secure-verifier")
        query = parse_qs(urlparse(url).query)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(b"a-secure-verifier").digest()
        ).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [expected])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["state"], ["state-value"])

    @patch("transfer.library_views._soundcloud_access")
    def test_import_soundcloud_playlist_preserves_track_metadata(self, access):
        client = Mock()
        client.resolve.return_value = {"kind": "playlist", "id": 123, "title": "SC Mix"}
        client.playlist_tracks.return_value = [{
            "id": 987,
            "title": "Track One",
            "duration": 185000,
            "metadata_artist": "Artist One",
            "permalink_url": "https://soundcloud.com/artist-one/track-one",
        }]
        access.return_value = (client, "sc-token")
        response = self.client.post(
            reverse("library_import_soundcloud_playlist"),
            {"source_url": "https://soundcloud.com/artist/mix"},
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryPlaylist, LibraryTrack
        playlist = LibraryPlaylist.objects.get(title="SC Mix", provider="soundcloud")
        track = LibraryTrack.objects.get(playlist=playlist)
        self.assertEqual(track.external_id, "987")
        self.assertEqual(track.duration_ms, 185000)
        self.assertEqual(track.artist, "Artist One")
        client.playlist_tracks.assert_called_once_with("sc-token", 123)

    @patch("transfer.library_views._soundcloud_access")
    def test_import_soundcloud_track_creates_single_track_collection(self, access):
        client = Mock()
        client.resolve.return_value = {
            "kind": "track",
            "id": 456,
            "title": "Single",
            "duration": 90000,
            "metadata_artist": "Artist",
            "permalink_url": "https://soundcloud.com/artist/single",
        }
        access.return_value = (client, "sc-token")
        response = self.client.post(
            reverse("library_import_soundcloud_track"),
            {"source_url": "https://soundcloud.com/artist/single"},
        )
        self.assertEqual(response.status_code, 302)
        from .models import LibraryTrack
        track = LibraryTrack.objects.get(external_id="456")
        self.assertEqual(track.title, "Single")
        self.assertEqual(track.duration_ms, 90000)

    @patch("transfer.library_views._soundcloud_access")
    def test_upload_owned_audio_file_to_soundcloud(self, access):
        client = Mock()
        client.upload_track.return_value = {
            "id": 321,
            "duration": 125000,
            "permalink_url": "https://soundcloud.com/me/uploaded-track",
        }
        access.return_value = (client, "sc-token")
        audio = SimpleUploadedFile("demo.mp3", b"audio-bytes", content_type="audio/mpeg")
        response = self.client.post(
            reverse("library_upload_soundcloud_track"),
            {"title": "Demo", "artist": "Me", "audio_file": audio},
        )
        self.assertEqual(response.status_code, 302)
        client.upload_track.assert_called_once()
        from .models import LibraryTrack
        track = LibraryTrack.objects.get(external_id="321")
        self.assertEqual(track.title, "Demo")

    @patch("transfer.library_views._spotify_access")
    def test_import_spotify_track_uses_official_track_endpoint(self, access):
        client = Mock()
        client.track_details.return_value = {
            "id": "1234567890123456789012",
            "type": "track",
            "name": "Spotify Track",
            "duration_ms": 180000,
            "artists": [{"name": "Artist"}],
            "external_urls": {"spotify": "https://open.spotify.com/track/1234567890123456789012"},
            "album": {"name": "Album"},
        }
        access.return_value = (client, "spotify-token")
        response = self.client.post(
            reverse("library_import_spotify_track"),
            {"source_url": "https://open.spotify.com/track/1234567890123456789012"},
        )
        self.assertEqual(response.status_code, 302)
        client.track_details.assert_called_once_with("spotify-token", "1234567890123456789012")
        from .models import LibraryTrack
        track = LibraryTrack.objects.get(external_id="1234567890123456789012")
        self.assertEqual(track.artist, "Artist")
        self.assertEqual(track.album, "Album")


class UnifiedLibraryTransferTests(TestCase):
    @patch("transfer.library_views.get_access_token", return_value=("sc-token", {}))
    @patch("transfer.library_views.SoundCloudClient")
    def test_unmatched_track_can_be_searched_and_added_manually(self, soundcloud_class, _token):
        from .credentials import get_session_fingerprint
        from .models import LibraryPlaylist, LibraryProfile, LibraryTrack, LibraryTransfer, LibraryTransferItem

        profile, _ = LibraryProfile.objects.get_or_create(
            session_fingerprint=get_session_fingerprint(self.client),
        )
        source = LibraryPlaylist.objects.create(profile=profile, title="Unmatched", provider="vk")
        LibraryTrack.objects.create(playlist=source, title="Unknown Track", artist="Unknown Artist", position=0)
        client = Mock()
        candidate = {
            "id": 988,
            "title": "Unknown Track",
            "metadata_artist": "Unknown Artist",
            "duration": 180000,
            "permalink_url": "https://soundcloud.com/artist/unknown-track",
        }
        client.search_tracks.side_effect = [[], [candidate]]
        client.create_playlist.return_value = {
            "id": 555,
            "permalink_url": "https://soundcloud.com/me/unmatched",
        }
        soundcloud_class.return_value = client

        response = self.client.post(
            reverse("library_transfer_playlist", kwargs={"playlist_id": source.pk}),
            {"target_provider": "soundcloud"},
        )
        self.assertEqual(response.status_code, 302)
        review = LibraryTransfer.objects.get(source_playlist=source)
        item = LibraryTransferItem.objects.get(transfer=review)
        self.assertEqual(item.status, LibraryTransferItem.Status.PENDING)

        self.client.post(
            reverse("search_transfer_item", kwargs={"transfer_id": review.pk, "item_id": item.pk}),
            {"query": "Unknown Artist Unknown Track"},
        )
        item.refresh_from_db()
        self.assertEqual(item.candidates[0]["id"], "988")

        response = self.client.post(
            reverse("select_transfer_candidate", kwargs={"transfer_id": review.pk, "item_id": item.pk}),
            {"candidate_id": "988"},
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(item.status, LibraryTransferItem.Status.MATCHED)
        self.assertEqual(review.status, LibraryTransfer.Status.COMPLETED)
        client.create_playlist.assert_called_once_with("sc-token", "Unmatched", ["988"])
        self.assertEqual(review.target_playlist.tracks.get().external_id, "988")

    @patch("transfer.library_views.get_access_token", return_value=("sc-token", {}))
    @patch("transfer.library_views.SoundCloudClient")
    def test_manual_candidate_id_not_in_server_results_is_rejected(self, soundcloud_class, _token):
        from .credentials import get_session_fingerprint
        from .models import LibraryPlaylist, LibraryProfile, LibraryTrack, LibraryTransfer, LibraryTransferItem

        profile, _ = LibraryProfile.objects.get_or_create(
            session_fingerprint=get_session_fingerprint(self.client),
        )
        source = LibraryPlaylist.objects.create(profile=profile, title="Private review", provider="vk")
        track = LibraryTrack.objects.create(playlist=source, title="Track", artist="Artist")
        review = LibraryTransfer.objects.create(
            profile=profile, source_playlist=source, target_provider="soundcloud",
            provider_playlist_id="555", total=1,
        )
        item = LibraryTransferItem.objects.create(
            transfer=review, source_track=track, position=0,
            candidates=[{"id": "988", "title": "Safe result", "uri": "988", "url": ""}],
        )
        client = Mock()
        soundcloud_class.return_value = client

        response = self.client.post(
            reverse("select_transfer_candidate", kwargs={"transfer_id": review.pk, "item_id": item.pk}),
            {"candidate_id": "attacker-controlled-id"},
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, LibraryTransferItem.Status.PENDING)
        client.update_playlist_tracks.assert_not_called()


    @patch("transfer.library_views.get_access_token", return_value=("sc-token", {}))
    @patch("transfer.library_views.SoundCloudClient")
    def test_transfer_library_playlist_to_soundcloud(self, soundcloud_class, _token):
        from .credentials import get_session_fingerprint
        from .models import LibraryPlaylist, LibraryProfile, LibraryTrack

        profile, _ = LibraryProfile.objects.get_or_create(
            session_fingerprint=get_session_fingerprint(self.client),
        )
        source = LibraryPlaylist.objects.create(
            profile=profile, title="Night Set", provider="vk",
        )
        LibraryTrack.objects.create(
            playlist=source, title="Track", artist="Artist", duration_ms=100000,
        )
        client = Mock()
        client.search_tracks.return_value = [{
            "id": 987,
            "title": "Track",
            "metadata_artist": "Artist",
            "duration": 100000,
            "permalink_url": "https://soundcloud.com/artist/track",
        }]
        client.create_playlist.return_value = {
            "id": 555,
            "permalink_url": "https://soundcloud.com/me/night-set",
        }
        soundcloud_class.return_value = client

        response = self.client.post(
            reverse("library_transfer_playlist", kwargs={"playlist_id": source.pk}),
            {"target_provider": "soundcloud"},
        )
        self.assertEqual(response.status_code, 302)
        target = LibraryPlaylist.objects.get(provider="soundcloud", title="Night Set · Soundcloud")
        transferred = LibraryTrack.objects.get(playlist=target)
        self.assertEqual(transferred.external_id, "987")
        self.assertEqual(transferred.external_url, "https://soundcloud.com/artist/track")
        client.create_playlist.assert_called_once_with("sc-token", "Night Set", ["987"])

    def test_vk_individual_track_url_parser(self):
        self.assertEqual(parse_vk_track_url("https://vk.com/audio-123_456"), (-123, 456))
        with self.assertRaises(ValueError):
            parse_vk_track_url("https://attacker.example/audio-123_456")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AccountWorkspaceTests(TestCase):
    def test_account_library_is_persistent_across_browser_sessions(self):
        from django.contrib.auth import get_user_model

        from .models import LibraryPlaylist, LibraryProfile

        user = get_user_model().objects.create_user(
            username="persistent_listener",
            password=TEST_PASSWORD,
        )
        first_browser = self.client_class()
        first_browser.force_login(user)
        first_browser.post(
            reverse("library_create_playlist"),
            {"title": "Across devices", "provider": "manual"},
        )
        playlist = LibraryPlaylist.objects.get(title="Across devices")

        second_browser = self.client_class()
        second_browser.force_login(user)
        response = second_browser.get(reverse("playlist_detail", kwargs={"playlist_id": playlist.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LibraryProfile.objects.filter(user=user).count(), 1)


    def test_registration_attaches_existing_guest_library_to_account(self):
        from .models import LibraryProfile

        self.client.post(
            reverse("library_create_playlist"),
            {"title": "Guest collection", "provider": "manual"},
        )
        profile = LibraryProfile.objects.get()
        self.assertIsNone(profile.user_id)

        response = self.client.post(
            reverse("register"),
            {
                "username": "listener_one",
                "email": "listener@example.test",
                "password1": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))
        profile.refresh_from_db()
        self.assertEqual(profile.user.username, "listener_one")
        self.assertEqual(profile.playlists.get().title, "Guest collection")

    def test_account_libraries_are_isolated_between_users(self):
        from django.contrib.auth import get_user_model

        from .models import LibraryPlaylist, LibraryProfile

        user_model = get_user_model()
        first = user_model.objects.create_user(
            username="listener_a",
            email="a@example.test",
            password=TEST_PASSWORD,
        )
        second = user_model.objects.create_user(
            username="listener_b",
            email="b@example.test",
            password=TEST_PASSWORD,
        )
        self.client.force_login(first)
        self.client.post(
            reverse("library_create_playlist"),
            {"title": "Private collection", "provider": "manual"},
        )
        playlist = LibraryPlaylist.objects.get(title="Private collection")
        self.client.logout()
        self.client.force_login(second)
        response = self.client.get(reverse("playlist_detail", kwargs={"playlist_id": playlist.pk}))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(LibraryProfile.objects.filter(user=first).count(), 1)
        self.assertEqual(LibraryProfile.objects.filter(user=second).count(), 1)

    def test_all_authenticated_pages_and_transfer_review_render(self):
        from django.contrib.auth import get_user_model

        from .models import LibraryPlaylist, LibraryProfile, LibraryTrack, LibraryTransfer, LibraryTransferItem

        user = get_user_model().objects.create_user(
            username="page_tester",
            password=TEST_PASSWORD,
        )
        self.client.force_login(user)
        for route_name in ("dashboard", "library", "connections", "transfers", "profile"):
            with self.subTest(page=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

        profile = LibraryProfile.objects.get(user=user)
        playlist = LibraryPlaylist.objects.create(profile=profile, title="Template test", provider="manual")
        track = LibraryTrack.objects.create(playlist=playlist, title="Review track", artist="Review artist")
        self.assertEqual(
            self.client.get(reverse("playlist_detail", kwargs={"playlist_id": playlist.pk})).status_code,
            200,
        )
        transfer = LibraryTransfer.objects.create(
            profile=profile,
            source_playlist=playlist,
            target_provider="spotify",
            provider_playlist_id="",
            total=1,
        )
        LibraryTransferItem.objects.create(
            transfer=transfer,
            source_track=track,
            position=0,
            candidates=[{"id": "123", "uri": "spotify:track:123", "title": "Candidate", "artist": "Artist", "url": ""}],
        )
        self.assertEqual(
            self.client.get(reverse("transfer_review", kwargs={"transfer_id": transfer.pk})).status_code,
            200,
        )

    def test_login_redirect_rejects_external_destination(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(
            username="listener_redirect",
            password=TEST_PASSWORD,
        )
        response = self.client.post(
            reverse("login") + "?next=https://evil.example/",
            {"username": "listener_redirect", "password": TEST_PASSWORD, "next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
