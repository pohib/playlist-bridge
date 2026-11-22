# Generated for the transfer job queue.
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="TransferJob",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("session_fingerprint", models.CharField(max_length=64, db_index=True)),
                ("source_url", models.URLField(max_length=2048)),
                ("target_playlist", models.CharField(max_length=128, blank=True)),
                ("encrypted_spotify_token", models.TextField()),
                ("status", models.CharField(max_length=16, choices=[("queued", "В очереди"), ("running", "Выполняется"), ("succeeded", "Завершено"), ("failed", "Ошибка")], default="queued", db_index=True)),
                ("progress", models.PositiveSmallIntegerField(default=0)),
                ("total", models.PositiveIntegerField(default=0)),
                ("matched", models.PositiveIntegerField(default=0)),
                ("not_found", models.PositiveIntegerField(default=0)),
                ("ambiguous", models.PositiveIntegerField(default=0)),
                ("result", models.JSONField(default=dict, blank=True)),
                ("error", models.CharField(max_length=500, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(null=True, blank=True)),
                ("finished_at", models.DateTimeField(null=True, blank=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
