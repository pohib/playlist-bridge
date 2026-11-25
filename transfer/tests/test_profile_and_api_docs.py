from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class ProfileProviderConnectionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="profile-provider-user", password="test-password")
        self.client.force_login(self.user)

    @override_settings(SPOTIFY_CLIENT_ID="spotify-id", SPOTIFY_CLIENT_SECRET="spotify-secret",
                       SOUNDCLOUD_CLIENT_ID="soundcloud-id", SOUNDCLOUD_CLIENT_SECRET="soundcloud-secret")
    def test_profile_contains_provider_connection_controls(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подключения аккаунтов")
        self.assertContains(response, reverse("spotify_login"))
        self.assertContains(response, reverse("soundcloud_login"))
        self.assertContains(response, "Публичный импорт")

    def test_legacy_connections_url_redirects_to_profile(self):
        response = self.client.get(reverse("connections"))
        self.assertRedirects(response, reverse("profile"))

    def test_library_keeps_import_surface(self):
        response = self.client.get(reverse("library"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("library_import_vk"))
        self.assertContains(response, reverse("library_import_spotify_track"))
        self.assertContains(response, reverse("library_import_soundcloud_track"))


class ApiDocumentationTests(TestCase):
    def test_api_docs_page_is_readable_without_login(self):
        response = self.client.get(reverse("api_docs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Документация")
        self.assertContains(response, "/api/v1/transfers/")
        self.assertContains(response, "X-CSRFToken")
        self.assertContains(response, "Не передавайте пароли")

    def test_api_docs_page_does_not_publish_credentials(self):
        response = self.client.get(reverse("api_docs"))
        self.assertNotContains(response, "client_secret=")
        self.assertNotContains(response, "access_token=")
        self.assertNotContains(response, "refresh_token=")

    def test_openapi_schema_does_not_advertise_provider_tokens(self):
        response = self.client.get(reverse("api_openapi"))
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertNotIn("access_token", str(schema))
        self.assertNotIn("refresh_token", str(schema))
