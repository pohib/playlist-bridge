from django.contrib.auth import get_user_model  # noqa: I001
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import LibraryPlaylist, LibraryProfile, LibraryTrack, OAuthCredential


TEST_STORAGE_SETTINGS = {
    "STORAGES": {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    "WHITENOISE_MANIFEST_STRICT": False,
}


@override_settings(**TEST_STORAGE_SETTINGS)
class ProfileProviderConnectionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="profile-provider-user", password="test-password")
        self.client.force_login(self.user)

    def test_profile_contains_account_overview_and_library_name_form(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Профиль")
        self.assertContains(response, "Имя музыкального профиля")
        self.assertContains(response, "profile-name-form")
        self.assertContains(response, "плейлистов в библиотеке")
        self.assertContains(response, reverse("connections"))
        self.assertNotContains(response, reverse("spotify_login"))

    def test_profile_shows_real_library_statistics_and_recent_playlists(self):
        response = self.client.get(reverse("profile"))
        profile = response.context["library_profile"]
        playlist = LibraryPlaylist.objects.create(
            profile=profile,
            title="Profile statistics playlist",
            provider=LibraryPlaylist.Provider.SPOTIFY,
        )
        LibraryTrack.objects.create(playlist=playlist, title="Track A", artist="Artist A")
        LibraryTrack.objects.create(playlist=playlist, title="Track B", artist="Artist B")

        response = self.client.get(reverse("profile"))
        self.assertEqual(response.context["playlist_count"], 1)
        self.assertEqual(response.context["track_count"], 2)
        self.assertContains(response, "Profile statistics playlist")
        self.assertContains(response, "2 треков")

    @override_settings(SPOTIFY_CLIENT_ID="spotify-id", SPOTIFY_CLIENT_SECRET="spotify-secret",
                       SOUNDCLOUD_CLIENT_ID="soundcloud-id", SOUNDCLOUD_CLIENT_SECRET="soundcloud-secret")
    def test_services_page_contains_provider_connection_controls(self):
        response = self.client.get(reverse("connections"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Музыкальные")
        self.assertContains(response, reverse("spotify_login"))
        self.assertContains(response, reverse("soundcloud_login"))
        self.assertContains(response, "Публичный импорт")

    @override_settings(SPOTIFY_CLIENT_ID="spotify-id", SPOTIFY_CLIENT_SECRET="spotify-secret",
                       SOUNDCLOUD_CLIENT_ID="soundcloud-id", SOUNDCLOUD_CLIENT_SECRET="soundcloud-secret")
    def test_services_page_reflects_connected_provider_credentials(self):
        self.client.get(reverse("profile"))
        profile = LibraryProfile.objects.get(user=self.user)
        OAuthCredential.objects.create(
            session_fingerprint=profile.session_fingerprint,
            provider="spotify",
            encrypted_payload="test-encrypted-payload",
        )
        response = self.client.get(reverse("connections"))
        self.assertContains(response, "Подключён")
        self.assertNotContains(response, reverse("spotify_login"))
        self.assertContains(response, reverse("soundcloud_login"))

    def test_services_page_is_available_from_navigation(self):
        response = self.client.get(reverse("connections"))
        self.assertContains(response, 'class="active">Сервисы</a>')
        self.assertContains(response, reverse("profile"))

    def test_library_keeps_import_surface(self):
        response = self.client.get(reverse("library"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("library_import_vk"))
        self.assertContains(response, reverse("library_import_spotify_track"))
        self.assertContains(response, reverse("library_import_soundcloud_track"))


@override_settings(**TEST_STORAGE_SETTINGS)
class PlayerAndProfileStyleRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(finders.find("transfer/styles/main.css"), encoding="utf-8") as stylesheet:
            cls.stylesheet = stylesheet.read()
        with open(finders.find("transfer/js/app.js"), encoding="utf-8") as player_script:
            cls.player_script = player_script.read()

    def test_collapsed_player_keeps_track_title_space_and_ellipsis(self):
        self.assertIn(".global-player.is-collapsed .global-player-meta{display:grid;flex:1 1 150px;min-width:72px;overflow:hidden}", self.stylesheet)
        self.assertIn(".global-player.is-collapsed .global-player-meta strong", self.stylesheet)
        self.assertIn("text-overflow:ellipsis", self.stylesheet)
        self.assertIn("width:min(520px,calc(100vw - 28px))", self.stylesheet)

    def test_player_uses_independent_translate_for_centering_and_flip_animation(self):
        self.assertIn("translate:-50% 0;", self.stylesheet)
        self.assertIn("translate:0 0;", self.stylesheet)
        self.assertIn("translate3d("+ "0,0,0) scale(1,1)", self.player_script)
        self.assertIn('prefers-reduced-motion: reduce', self.player_script)
        self.assertIn('animation.addEventListener("finish",cleanup,{once:true})', self.player_script)
        self.assertIn('animation.addEventListener("cancel",cleanup,{once:true})', self.player_script)

    def test_account_chip_has_full_box_geometry(self):
        self.assertIn(".account-chip { display:flex; align-items:center; gap:8px; min-height:43px; padding:5px 11px;", self.stylesheet)
        self.assertIn("border-radius:13px", self.stylesheet)

    def test_profile_name_heading_and_input_have_separate_layout(self):
        self.assertIn(".profile-section-heading", self.stylesheet)
        self.assertIn(".profile-name-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;", self.stylesheet)


@override_settings(**TEST_STORAGE_SETTINGS)
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
