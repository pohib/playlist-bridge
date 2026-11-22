import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


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
        constraints = [
            models.UniqueConstraint(
                fields=("session_fingerprint",),
                condition=Q(status__in=("queued", "running")),
                name="one_active_transfer_per_session",
            ),
        ]


class LibraryProfile(models.Model):
    """A persistent account workspace, with legacy anonymous-session support."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="library_profile")
    display_name = models.CharField(max_length=60, default="Моя музыкальная библиотека")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name


class LibraryPlaylist(models.Model):
    class Provider(models.TextChoices):
        VK = "vk", "ВКонтакте"
        SPOTIFY = "spotify", "Spotify"
        SOUNDCLOUD = "soundcloud", "SoundCloud"
        YOUTUBE_MUSIC = "youtube_music", "YouTube Music"
        APPLE_MUSIC = "apple_music", "Apple Music"
        MANUAL = "manual", "Локальная коллекция"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(LibraryProfile, on_delete=models.CASCADE, related_name="playlists")
    title = models.CharField(max_length=120)
    provider = models.CharField(max_length=24, choices=Provider.choices, default=Provider.MANUAL)
    external_url = models.URLField(max_length=2048, blank=True)
    description = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.title


class LibraryTrack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    playlist = models.ForeignKey(LibraryPlaylist, on_delete=models.CASCADE, related_name="tracks")
    title = models.CharField(max_length=180)
    artist = models.CharField(max_length=180)
    album = models.CharField(max_length=180, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    external_id = models.CharField(max_length=200, blank=True)
    external_url = models.URLField(max_length=2048, blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "created_at")

    def __str__(self):
        return f"{self.artist} — {self.title}"
