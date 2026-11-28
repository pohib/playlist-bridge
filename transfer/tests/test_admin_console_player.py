from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsolePlayerIntegrationTests(TestCase):
    def test_control_center_includes_shared_player_and_runtime(self):
        root = get_user_model().objects.create_superuser(
            username="player-admin",
            email="player-admin@example.test",
            password="test-password",
        )
        self.client.force_login(root)

        response = self.client.get(reverse("admin_console"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="global-player"', html)
        self.assertIn('id="player-audio"', html)
        self.assertIn('id="player-queue-panel"', html)
        self.assertIn('id="player-eq-panel"', html)
        self.assertEqual(html.count('data-eq-frequency-knob='), 5)
        self.assertEqual(html.count('data-eq-q-knob='), 5)
        self.assertIn('id="player-queue-close"', html)
        self.assertIn("transfer/js/app.js", html)
        self.assertIn("transfer/styles/main.css", html)
        self.assertIn("transfer/styles/admin-console.css", html)
