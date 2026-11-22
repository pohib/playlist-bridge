from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("transfer", "0002_oauthcredential")]

    operations = [
        migrations.AddConstraint(
            model_name="transferjob",
            constraint=models.UniqueConstraint(
                fields=("session_fingerprint",),
                condition=Q(status__in=("queued", "running")),
                name="one_active_transfer_per_session",
            ),
        ),
    ]
