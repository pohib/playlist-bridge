import base64
import hashlib
import hmac
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from requests import HTTPError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .core import ReauthorizationRequired, SpotifyClient, VKIDClient, normalize_track_text, parse_vk_playlist_url
from .credentials import decrypt_payload, get_access_token, store_credential
from .models import OAuthCredential, TransferJob


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
        client.get(reverse("home"))
        session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
        return hmac.new(
            settings.SECRET_KEY.encode(), session_key.encode(), hashlib.sha256
        ).hexdigest()

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
        self.client.get(reverse("home"))
        session_key = self.client.session.session_key
        fingerprint = hmac.new(
            settings.SECRET_KEY.encode(), session_key.encode(), hashlib.sha256
        ).hexdigest()
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
        client = SpotifyClient("client-id", "client-secret", "https://example.test/callback/")
        response = Mock()
        response.raise_for_status.side_effect = HTTPError("invalid_grant")
        response.json.return_value = {"error": "invalid_grant"}
        client.http.post = Mock(return_value=response)

        with self.assertRaises(ReauthorizationRequired):
            client.refresh_token("expired-refresh-token")

