import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="OAuthCredential",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("session_fingerprint", models.CharField(max_length=64, db_index=True)),
                ("provider", models.CharField(max_length=16, choices=[("vk", "VK"), ("spotify", "Spotify")])),
                ("encrypted_payload", models.TextField()),
                ("external_user_id", models.CharField(max_length=128, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="oauthcredential",
            constraint=models.UniqueConstraint(fields=("session_fingerprint", "provider"), name="unique_oauth_credential_per_session_provider"),
        ),
        migrations.RemoveField(model_name="transferjob", name="encrypted_spotify_token"),
    ]
