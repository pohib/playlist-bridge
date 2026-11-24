import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .credentials import get_session_fingerprint
from .models import LibraryPlaylist, LibraryProfile, LibraryTrack
from .services import TransferError


class VKPlaybackApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="vk-playback-user", password="test-password")
        self.client.force_login(self.user)
        self.profile, _ = LibraryProfile.objects.get_or_create(
            user=self.user,
            defaults={"session_fingerprint": get_session_fingerprint(self.client)},
        )
        self.playlist = LibraryPlaylist.objects.create(
            profile=self.profile,
            title="VK playback tests",
            provider=LibraryPlaylist.Provider.VK,
            external_url="https://vk.ru/music/playlist/10_5_access",
        )
        self.track = LibraryTrack.objects.create(
            playlist=self.playlist,
            title="Test track",
            artist="Test artist",
            external_id="10_101",
            source_provider=LibraryPlaylist.Provider.VK,
        )
        self.stream_url = reverse("library_vk_track_stream", kwargs={"track_id": self.track.pk})
        self.audio_url = reverse("library_vk_track_audio", kwargs={"track_id": self.track.pk})

    def test_stream_resolution_returns_fresh_mp3_url_without_cache(self):
        with patch("transfer.library_views.VKClient") as client_class:
            client = client_class.return_value
            client.get_track_stream.return_value = {
                "url": "https://cdn.okcdn.ru/audio.mp3",
                "format": "mp3",
            }
            response = self.client.post(
                self.stream_url,
                data=json.dumps({"format": "mp3"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["format"], "mp3")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Pragma"], "no-cache")
        client.get_track_stream.assert_called_once_with("10_101", "mp3")

    def test_stream_resolution_returns_422_when_vk_has_no_mp3_stream(self):
        with patch("transfer.library_views.VKClient") as client_class:
            client_class.return_value.get_track_stream.side_effect = TransferError(
                "VK не предоставил поток в формате mp3."
            )
            response = self.client.post(
                self.stream_url,
                data=json.dumps({"format": "mp3"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("не предоставил поток", response.json()["error"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_stream_resolution_rejects_malformed_json(self):
        response = self.client.post(self.stream_url, data="{", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Некорректный запрос", response.json()["error"])

    def test_stream_resolution_rejects_unsupported_format(self):
        response = self.client.post(
            self.stream_url,
            data=json.dumps({"format": "dash"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Неподдерживаемый формат", response.json()["error"])

    def test_stream_resolution_rejects_non_vk_track(self):
        self.track.source_provider = LibraryPlaylist.Provider.SPOTIFY
        self.track.save(update_fields=["source_provider"])

        with patch("transfer.library_views.VKClient") as client_class:
            response = self.client.post(
                self.stream_url,
                data=json.dumps({"format": "mp3"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        client_class.assert_not_called()

    def test_stream_resolution_rejects_another_users_track(self):
        other_user = get_user_model().objects.create_user(
            username="vk-playback-other",
            password="test-password",
        )
        other_profile = LibraryProfile.objects.create(
            user=other_user,
            session_fingerprint="b" * 64,
        )
        other_playlist = LibraryPlaylist.objects.create(
            profile=other_profile,
            title="Private VK playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        other_track = LibraryTrack.objects.create(
            playlist=other_playlist,
            title="Private track",
            artist="Private artist",
            external_id="10_202",
            source_provider=LibraryPlaylist.Provider.VK,
        )

        response = self.client.post(
            reverse("library_vk_track_stream", kwargs={"track_id": other_track.pk}),
            data=json.dumps({"format": "mp3"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_stream_resolution_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            self.stream_url,
            data=json.dumps({"format": "mp3"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

    def test_audio_proxy_returns_structured_422_when_mp3_is_unavailable(self):
        with patch("transfer.library_views.VKClient") as client_class:
            client_class.return_value.get_track_stream.side_effect = TransferError(
                "VK не предоставил поток в формате mp3."
            )
            with patch("requests.get") as upstream:
                response = self.client.get(self.audio_url)

        self.assertEqual(response.status_code, 422)
        self.assertIn("не предоставил поток", response.json()["error"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        upstream.assert_not_called()

    def test_audio_proxy_forwards_range_and_streams_partial_content(self):
        upstream_response = Mock()
        upstream_response.status_code = 206
        upstream_response.headers = {
            "Content-Range": "bytes 0-4/100",
            "Content-Length": "5",
            "Accept-Ranges": "bytes",
        }
        upstream_response.iter_content.return_value = [b"audio", b""]

        with (
            patch("transfer.library_views.VKClient") as client_class,
            patch("requests.get", return_value=upstream_response) as upstream,
        ):
            api = client_class.return_value
            api.token_provider.BROWSER_HEADERS = {"User-Agent": "test-agent"}
            api.token_provider.referer = self.playlist.external_url
            api.get_track_stream.return_value = {
                "url": "https://cdn.okcdn.ru/audio.mp3",
                "format": "mp3",
            }
            response = self.client.get(self.audio_url, HTTP_RANGE="bytes=0-4")
            content = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Type"], "audio/mpeg")
        self.assertEqual(response["Content-Range"], "bytes 0-4/100")
        self.assertEqual(response["Content-Length"], "5")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(content, b"audio")
        self.assertEqual(upstream.call_args.kwargs["headers"]["Range"], "bytes=0-4")
        self.assertIs(upstream.call_args.kwargs["allow_redirects"], False)
        upstream_response.close.assert_called_once()

    def test_audio_proxy_rejects_partial_response_without_content_range(self):
        upstream_response = Mock(status_code=206, headers={})
        with (
            patch("transfer.library_views.VKClient") as client_class,
            patch("requests.get", return_value=upstream_response),
        ):
            client_class.return_value.token_provider.BROWSER_HEADERS = {}
            client_class.return_value.token_provider.BROWSER_HEADERS = {}
            client_class.return_value.get_track_stream.return_value = {
                "url": "https://cdn.okcdn.ru/audio.mp3",
                "format": "mp3",
            }
            response = self.client.get(self.audio_url)

        self.assertEqual(response.status_code, 502)
        upstream_response.close.assert_called_once()

    def test_audio_proxy_returns_502_when_cdn_connection_fails(self):
        import requests

        with (
            patch("transfer.library_views.VKClient") as client_class,
            patch("requests.get", side_effect=requests.RequestException("connection failed")),
        ):
            client_class.return_value.get_track_stream.return_value = {
                "url": "https://cdn.okcdn.ru/audio.mp3",
                "format": "mp3",
            }
            response = self.client.get(self.audio_url)

        self.assertEqual(response.status_code, 502)
        self.assertIn("CDN VK", response.json()["error"])

    def test_audio_proxy_closes_unusable_upstream_response(self):
        upstream_response = Mock(status_code=403, headers={})
        with (
            patch("transfer.library_views.VKClient") as client_class,
            patch("requests.get", return_value=upstream_response),
        ):
            client_class.return_value.get_track_stream.return_value = {
                "url": "https://cdn.okcdn.ru/audio.mp3",
                "format": "mp3",
            }
            response = self.client.get(self.audio_url)

        self.assertEqual(response.status_code, 502)
        upstream_response.close.assert_called_once()

    def test_audio_proxy_rejects_non_vk_track(self):
        self.track.source_provider = LibraryPlaylist.Provider.SPOTIFY
        self.track.save(update_fields=["source_provider"])

        with patch("transfer.library_views.VKClient") as client_class:
            response = self.client.get(self.audio_url)

        self.assertEqual(response.status_code, 404)
        client_class.assert_not_called()

    def test_audio_proxy_rejects_another_users_track(self):
        other_profile = LibraryProfile.objects.create(
            session_fingerprint="c" * 64,
        )
        other_playlist = LibraryPlaylist.objects.create(
            profile=other_profile,
            title="Another user's playlist",
            provider=LibraryPlaylist.Provider.VK,
        )
        other_track = LibraryTrack.objects.create(
            playlist=other_playlist,
            title="Private track",
            artist="Private artist",
            external_id="10_303",
            source_provider=LibraryPlaylist.Provider.VK,
        )

        with patch("transfer.library_views.VKClient") as client_class:
            response = self.client.get(
                reverse("library_vk_track_audio", kwargs={"track_id": other_track.pk})
            )

        self.assertEqual(response.status_code, 404)
        client_class.assert_not_called()

    def test_audio_proxy_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.audio_url)
        self.assertEqual(response.status_code, 302)

class VKTrackStreamValidationTests(TestCase):
    def setUp(self):
        from .services.vk_client import VKClient

        self.client = VKClient(version="5.289")

    def test_mp3_stream_is_extracted_from_vk_response(self):
        self.client.post = Mock(return_value={
            "response": [{
                "audio_streams": [{
                    "type": "mp3",
                    "url": "https://cdn.okcdn.ru/audio.mp3",
                }],
            }],
        })

        result = self.client.get_track_stream("10_101", "mp3")

        self.assertEqual(
            result,
            {"url": "https://cdn.okcdn.ru/audio.mp3", "format": "mp3"},
        )
        self.client.post.assert_called_once_with("audio.getById", data={"audios": "10_101"})

    def test_missing_requested_stream_format_is_reported(self):
        self.client.post = Mock(return_value={
            "response": [{
                "audio_streams": [{
                    "type": "hls_ts",
                    "url": "https://cdn.okcdn.ru/audio.m3u8",
                }],
            }],
        })

        with self.assertRaisesRegex(TransferError, "формате mp3"):
            self.client.get_track_stream("10_101", "mp3")

    def test_restricted_track_has_distinct_error(self):
        self.client.post = Mock(return_value={
            "response": [{"content_restricted": True, "audio_streams": []}],
        })

        with self.assertRaisesRegex(TransferError, "ограничение доступа"):
            self.client.get_track_stream("10_101", "mp3")

    def test_untrusted_cdn_host_is_rejected(self):
        self.client.post = Mock(return_value={
            "response": [{
                "audio_streams": [{
                    "type": "mp3",
                    "url": "https://cdn.attacker.example/audio.mp3",
                }],
            }],
        })

        with self.assertRaisesRegex(TransferError, "небезопасный адрес"):
            self.client.get_track_stream("10_101", "mp3")

    def test_non_https_cdn_url_is_rejected(self):
        self.client.post = Mock(return_value={
            "response": [{
                "audio_streams": [{
                    "type": "mp3",
                    "url": "http://cdn.okcdn.ru/audio.mp3",
                }],
            }],
        })

        with self.assertRaisesRegex(TransferError, "небезопасный адрес"):
            self.client.get_track_stream("10_101", "mp3")

    def test_invalid_audio_id_and_stream_format_are_rejected_before_request(self):
        self.client.post = Mock()

        with self.assertRaisesRegex(TransferError, "идентификатор"):
            self.client.get_track_stream("../../admin", "mp3")
        with self.assertRaisesRegex(TransferError, "формат"):
            self.client.get_track_stream("10_101", "dash")

        self.client.post.assert_not_called()

