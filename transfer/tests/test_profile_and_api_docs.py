from django.conf import settings  # noqa: I001
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import AdminAuditEvent, LibraryPlaylist, LibraryProfile, LibraryTrack, OAuthCredential


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
        with open(settings.BASE_DIR / "transfer/templates/transfer/base.html", encoding="utf-8") as player_template:
            cls.player_template = player_template.read()

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

    def test_equalizer_exposes_per_band_q_knobs_and_wheel_control(self):
        self.assertIn('data-eq-q-knob="0"', self.player_template)
        self.assertIn('data-eq-q-value="4"', self.player_template)
        self.assertIn('state.eqQs=Array.isArray(state.eqQs)', self.player_script)
        self.assertIn('f.Q.setTargetAtTime(state.eqQs[i]', self.player_script)
        self.assertIn('addEventListener("wheel"', self.player_script)
        self.assertIn('nearest.distance>22', self.player_script)
        self.assertIn('player-eq-q-knob', self.stylesheet)
        self.assertIn('font-size:8px;font-weight:950', self.stylesheet)

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

    @override_settings(DEBUG=False)
    def test_unknown_api_routes_return_json_404(self):
        response = self.client.get("/api/v1/does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"error": {"message": "API endpoint not found."}})



@override_settings(**TEST_STORAGE_SETTINGS)
class LandingAndAdminConsoleTests(TestCase):
    def test_api_documentation_link_is_on_landing_page_after_profile_action(self):
        user = get_user_model().objects.create_user(
            username="landing-docs-user", password="test-password"
        )
        self.client.force_login(user)
        landing = self.client.get(reverse("home"))
        self.assertEqual(landing.status_code, 200)
        content = landing.content
        self.assertLess(content.index("Открыть мою библиотеку".encode()), content.index("Мой профиль".encode()))
        self.assertLess(content.index("Мой профиль".encode()), content.index("Документация API".encode()))

        dashboard = self.client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, reverse("api_docs"))

    def test_api_documentation_link_remains_public_for_anonymous_visitors(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("api_docs"))

    def test_admin_console_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_non_staff_user_cannot_access_admin_console(self):
        user = get_user_model().objects.create_user(
            username="regular-console-user", password="test-password"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_staff_user_can_access_custom_console_and_legacy_admin_redirects(self):
        user = get_user_model().objects.create_superuser(
            username="console-admin", email="admin@example.test", password="test-password"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("admin_console"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Состояние платформы")
        self.assertNotContains(response, "encrypted_payload")
        legacy_admin = self.client.get("/admin/")
        self.assertEqual(legacy_admin.status_code, 302)
        self.assertEqual(legacy_admin.url, "/control/")

    def test_admin_user_toggle_is_post_only_and_audited(self):
        admin_user = get_user_model().objects.create_superuser(
            username="console-operator", email="operator@example.test", password="test-password"
        )
        target = get_user_model().objects.create_user(
            username="target-user", password="test-password"
        )
        self.client.force_login(admin_user)
        response = self.client.post(reverse("admin_console_toggle_user", args=[target.pk]))
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        event = AdminAuditEvent.objects.get(target_id=str(target.pk))
        self.assertEqual(event.action, "user.deactivated")
        self.assertEqual(event.actor, admin_user)
        self.assertEqual(
            self.client.post(reverse("admin_console_toggle_user", args=[admin_user.pk])).status_code,
            403,
        )

    def test_staff_without_permissions_cannot_view_global_admin_data(self):
        staff = get_user_model().objects.create_user(
            username="restricted-staff", password="test-password", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin_console")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin_console_users")).status_code, 403)
