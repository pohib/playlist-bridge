from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from transfer.models import ProviderIntegrationEvent


class IntegrationEventRetentionTests(TestCase):
    def setUp(self):
        self.expired = ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.SPOTIFY,
            operation="oauth_callback",
            category=ProviderIntegrationEvent.Category.AUTH,
            message="Expired integration event",
        )
        self.current = ProviderIntegrationEvent.objects.create(
            provider=ProviderIntegrationEvent.Provider.VK,
            operation="search",
            category=ProviderIntegrationEvent.Category.NETWORK,
            message="Current integration event",
        )
        ProviderIntegrationEvent.objects.filter(pk=self.expired.pk).update(
            created_at=timezone.now() - timedelta(days=45)
        )

    @override_settings(INTEGRATION_EVENT_RETENTION_DAYS=30)
    def test_command_deletes_only_events_older_than_retention_period(self):
        output = StringIO()
        call_command("purge_integration_events", stdout=output)
        self.assertFalse(ProviderIntegrationEvent.objects.filter(pk=self.expired.pk).exists())
        self.assertTrue(ProviderIntegrationEvent.objects.filter(pk=self.current.pk).exists())
        self.assertIn("Удалено просроченных событий интеграций: 1", output.getvalue())

    def test_dry_run_does_not_delete_events(self):
        output = StringIO()
        call_command("purge_integration_events", "--days=30", "--dry-run", stdout=output)
        self.assertTrue(ProviderIntegrationEvent.objects.filter(pk=self.expired.pk).exists())
        self.assertIn("найдено просроченных событий интеграций — 1", output.getvalue())

    def test_invalid_retention_period_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("purge_integration_events", "--days=0")
