from django.db import models
import uuid


class OAuthCredential(models.Model):
    class Provider(models.TextChoices):
        VK = "vk", "VK"
        SPOTIFY = "spotify", "Spotify"
        SOUNDCLOUD = "soundcloud", "SoundCloud"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_fingerprint = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=16, choices=Provider.choices)
    encrypted_payload = models.TextField()
    external_user_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("session_fingerprint", "provider"),
                name="unique_oauth_credential_per_session_provider",
            ),
        ]
