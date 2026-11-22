import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0006_user_accounts")]

    operations = [
        migrations.CreateModel(
            name="LibraryTransfer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("target_provider", models.CharField(choices=[("vk", "ВКонтакте"), ("spotify", "Spotify"), ("soundcloud", "SoundCloud"), ("youtube_music", "YouTube Music"), ("apple_music", "Apple Music"), ("manual", "Локальная коллекция")], max_length=24)),
                ("target_playlist_id", models.CharField(max_length=128)),
                ("target_url", models.URLField(blank=True, max_length=2048)),
                ("status", models.CharField(choices=[("review", "Требует проверки"), ("completed", "Завершён")], default="review", max_length=16)),
                ("total", models.PositiveIntegerField(default=0)),
                ("matched", models.PositiveIntegerField(default=0)),
                ("skipped", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transfers", to="transfer.libraryprofile")),
                ("source_playlist", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transfers", to="transfer.libraryplaylist")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="LibraryTransferItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("position", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("pending", "Требует сопоставления"), ("matched", "Добавлен"), ("skipped", "Пропущен")], default="pending", max_length=12)),
                ("candidates", models.JSONField(blank=True, default=list)),
                ("target_external_id", models.CharField(blank=True, max_length=200)),
                ("target_url", models.URLField(blank=True, max_length=2048)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_track", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transfer_items", to="transfer.librarytrack")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="transfer.librarytransfer")),
            ],
            options={"ordering": ("position",)},
        ),
        migrations.AddConstraint(
            model_name="librarytransferitem",
            constraint=models.UniqueConstraint(fields=("transfer", "source_track"), name="unique_source_track_per_library_transfer"),
        ),
    ]
