import uuid

from django.conf import settings
from django.db import models


class AdminAuditEvent(models.Model):
    """Append-only record of privileged actions in the custom control panel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="playlist_bridge_admin_events",
    )
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "событие панели управления"
        verbose_name_plural = "события панели управления"

    def __str__(self):
        return f"{self.action} · {self.created_at:%Y-%m-%d %H:%M}"
