from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from transfer.models import ProviderIntegrationEvent, TransferJob
from transfer.services.integration_event_recorder import (
    classify_integration_error,
    record_transfer_failure,
    record_worker_failure,
    sanitize_integration_message,
)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminConsoleIntegrationEventTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="integration-staff", password="test-password", is_staff=True
        )
        self.superuser = user_model.objects.create_superuser(
            username="integration-root", email="root@example.test", password="test-password"
        )
        self.job = TransferJob.objects.create(
            session_fingerprint="integration-event-fingerprint",
            source_url="https://vk.com/music/playlist/1_2",
        )

    def test_staff_cannot_view_integration_diagnostics(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin_console_integrations"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_filter_integration_events(self):
        ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.SPOTIFY,
            operation="run_transfer",
            category=ProviderIntegrationEvent.Category.AUTH,
            message="Spotify authorization failed",
            transfer_job=self.job,
        )
        ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.VK,
            operation="run_transfer",
            category=ProviderIntegrationEvent.Category.NETWORK,
            message="VK connection timed out",
            transfer_job=self.job,
        )
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("admin_console_integrations"),
            {"provider": "spotify", "category": "auth"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertEqual(response.context["page"].object_list[0].provider, "spotify")
        self.assertContains(response, "Spotify authorization failed")
        self.assertNotContains(response, "VK connection timed out")

    def test_integration_event_summary_is_global_not_filter_dependent(self):
        ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.SPOTIFY,
            operation="run_transfer",
            category=ProviderIntegrationEvent.Category.AUTH,
            message="Spotify authorization failed",
        )
        ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.VK,
            operation="run_transfer",
            category=ProviderIntegrationEvent.Category.NETWORK,
            message="VK connection timed out",
        )
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("admin_console_integrations"), {"provider": "spotify"}
        )
        self.assertEqual(response.context["summary"]["total"], 2)
        self.assertEqual(response.context["summary"]["spotify"], 1)
        self.assertEqual(response.context["summary"]["vk"], 1)

    def test_failure_recorder_redacts_secrets_and_classifies_provider(self):
        error = RuntimeError(
            "Spotify API failed: Authorization: Bearer very-secret-token "
            "access_token=second-secret https://api.spotify.test/path?client_secret=url-secret"
        )
        event = record_transfer_failure(job=self.job, error=error)

        self.assertIsNotNone(event)
        self.assertEqual(event.provider, ProviderIntegrationEvent.Provider.SPOTIFY)
        self.assertEqual(event.category, ProviderIntegrationEvent.Category.AUTH)
        self.assertNotIn("very-secret-token", event.message)
        self.assertNotIn("second-secret", event.message)
        self.assertNotIn("url-secret", event.message)
        self.assertIn("[скрыто]", event.message)
        self.assertIn("[параметры скрыты]", event.message)

    def test_worker_failure_is_recorded_with_sanitized_message(self):
        event = record_worker_failure(
            job_id=self.job.pk,
            error=RuntimeError("Redis connection failed with password=worker-secret"),
            operation="dispatch_transfer_job",
        )

        self.assertEqual(event.category, ProviderIntegrationEvent.Category.WORKER)
        self.assertEqual(event.provider, ProviderIntegrationEvent.Provider.TRANSFER)
        self.assertEqual(event.transfer_job_id, self.job.pk)
        self.assertNotIn("worker-secret", event.message)
    def test_message_sanitizer_redacts_json_credential_values(self):
        safe = sanitize_integration_message(
            '{"access_token": "json-access-secret", "client_secret": "json-client-secret"}'
        )
        self.assertNotIn("json-access-secret", safe)
        self.assertNotIn("json-client-secret", safe)
        self.assertIn("[скрыто]", safe)

    def test_network_errors_are_classified(self):
        error = TimeoutError("Spotify request timed out")
        self.assertEqual(
            classify_integration_error(error),
            ProviderIntegrationEvent.Category.NETWORK,
        )

    def test_message_sanitizer_removes_bearer_and_query_credentials(self):
        safe = sanitize_integration_message(
            "Authorization: Bearer bearer-secret https://vk.com/api?access_token=query-secret"
        )
        self.assertNotIn("bearer-secret", safe)
        self.assertNotIn("query-secret", safe)
