from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsoleSystemTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="system-staff", password="test-password", is_staff=True
        )
        self.superuser = user_model.objects.create_superuser(
            username="system-root", email="root@example.test", password="test-password"
        )

    def test_regular_staff_cannot_view_system_diagnostics(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_system"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_diagnostics_identify_active_database_backend(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_console_system"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["database_backend"], "SQLite")
        self.assertTrue(response.context["database_backend_is_sqlite"])

    def test_provider_catalog_configuration_is_reported_without_exposing_credentials(self):
        with override_settings(
            SPOTIFY_CLIENT_ID="spotify-client-id",
            SPOTIFY_CLIENT_SECRET="spotify-client-secret",
            SOUNDCLOUD_CLIENT_ID="",
            SOUNDCLOUD_CLIENT_SECRET="",
        ):
            self.client.force_login(self.superuser)
            response = self.client.get(reverse("admin_console_system"))

        self.assertEqual(response.status_code, 200)
        integrations = {item["name"]: item for item in response.context["integrations"]}
        self.assertEqual(integrations["Spotify · поиск по каталогу"]["state_label"], "Реквизиты заданы")
        self.assertEqual(integrations["SoundCloud · поиск по каталогу"]["state_label"], "Не настроено")
        self.assertEqual(integrations["YouTube Music"]["state_label"], "Только ссылка")
        self.assertEqual(integrations["Apple Music"]["state_label"], "Только ссылка")
        self.assertNotContains(response, "spotify-client-secret")

    @patch("transfer.admin_console_views._system_check_celery_workers", return_value={
        "status": "warning", "label": "Celery workers", "detail": "Нет активных worker."
    })
    @patch("transfer.admin_console_views._system_check_celery_broker", return_value={
        "status": "ok", "label": "Celery broker", "detail": "Брокер доступен."
    })
    @patch("transfer.admin_console_views._system_check_cache", return_value={
        "status": "ok", "label": "Redis / кэш", "detail": "Кэш доступен."
    })
    @patch("transfer.admin_console_views._system_check_database", return_value={
        "status": "ok", "label": "База данных", "detail": "База доступна."
    })
    def test_superuser_can_view_system_diagnostics_without_secret_values(self, *_mocks):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_console_system"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "База данных")
        self.assertContains(response, "Spotify")
        self.assertContains(response, "SoundCloud")
        self.assertNotContains(response, "TOKEN_ENCRYPTION_KEY")
        self.assertNotContains(response, "root@example.test")
