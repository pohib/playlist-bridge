from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def close_duplicate_active_jobs(apps, schema_editor):
    TransferJob = apps.get_model("transfer", "TransferJob")
    fingerprints = (
        TransferJob.objects.filter(status__in=("queued", "running"))
        .values_list("session_fingerprint", flat=True)
        .distinct()
    )
    for fingerprint in fingerprints.iterator():
        active = list(
            TransferJob.objects.filter(
                session_fingerprint=fingerprint,
                status__in=("queued", "running"),
            ).order_by("created_at", "id")
        )
        duplicate_ids = [job.pk for job in active[1:]]
        if duplicate_ids:
            TransferJob.objects.filter(pk__in=duplicate_ids).update(
                status="failed",
                error="Закрыта дублирующаяся активная задача при обновлении схемы.",
                finished_at=timezone.now(),
            )


class Migration(migrations.Migration):
    dependencies = [("transfer", "0002_oauthcredential")]

    operations = [
        migrations.RunPython(close_duplicate_active_jobs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="transferjob",
            constraint=models.UniqueConstraint(
                fields=("session_fingerprint",),
                condition=Q(status__in=("queued", "running")),
                name="one_active_transfer_per_session",
            ),
        ),
    ]
