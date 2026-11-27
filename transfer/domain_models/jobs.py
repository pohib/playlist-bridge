import uuid

from django.db import models
from django.db.models import Q


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
    heartbeat_at = models.DateTimeField(null=True, blank=True)
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
