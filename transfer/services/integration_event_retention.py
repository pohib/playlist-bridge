"""Retention policy for provider integration diagnostics."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from transfer.models import ProviderIntegrationEvent


def purge_integration_events(*, days=None, dry_run=False):
    retention_days = (
        days if days is not None else settings.INTEGRATION_EVENT_RETENTION_DAYS
    )
    if retention_days < 1:
        raise ValueError("Retention period must be at least one day.")
    cutoff = timezone.now() - timedelta(days=retention_days)
    expired = ProviderIntegrationEvent.objects.filter(created_at__lt=cutoff)
    matched = expired.count()
    deleted = 0
    if not dry_run and matched:
        deleted, _details = expired.delete()
    return {"days": retention_days, "matched": matched, "deleted": deleted}
