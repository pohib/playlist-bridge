import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0003_one_active_transfer_per_session")]

    operations = [
        migrations.CreateModel(
            name="LibraryProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session_fingerprint", models.CharField(db_index=True, max_length=64, unique=True)),
                ("display_name", models.CharField(default="Моя музыкальная библиотека", max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="LibraryPlaylist",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=120)),
                ("provider", models.CharField(choices=[("vk", "ВКонтакте"), ("spotify", "Spotify"), ("youtube_music", "YouTube Music"), ("apple_music", "Apple Music"), ("manual", "Локальная коллекция")], default="manual", max_length=24)),
                ("external_url", models.URLField(blank=True, max_length=2048)),
                ("description", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="playlists", to="transfer.libraryprofile")),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="LibraryTrack",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=180)),
                ("artist", models.CharField(max_length=180)),
                ("album", models.CharField(blank=True, max_length=180)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("external_id", models.CharField(blank=True, max_length=200)),
                ("external_url", models.URLField(blank=True, max_length=2048)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("playlist", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tracks", to="transfer.libraryplaylist")),
            ],
            options={"ordering": ("position", "created_at")},
        ),
    ]
