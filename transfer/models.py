import uuid

from django.db import models


class OAuthCredential(models.Model):
    class Provider(models.TextChoices):
        VK = "vk", "VK"
        SPOTIFY = "spotify", "Spotify"

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


class TransferJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Завершено"
        FAILED = "failed", "Ошибка"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_fingerprint = models.CharField(max_length=64, db_index=True)
    source_url = models.URLField(max_length=2048)
    target_playlist = models.CharField(max_length=2048, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    matched = models.PositiveIntegerField(default=0)
    not_found = models.PositiveIntegerField(default=0)
    ambiguous = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
