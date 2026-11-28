import uuid

from django.conf import settings
from django.db import models


class AdminAuditEvent(models.Model):
    """Append-only record of privileged actions in the custom control panel."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="playlist_bridge_admin_events")
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


class UserSecurityEvent(models.Model):
    """Login telemetry visible only to superusers in the custom control panel."""
    class EventType(models.TextChoices):
        LOGIN_SUCCEEDED = "login_succeeded", "Успешный вход"
        LOGIN_FAILED = "login_failed", "Неудачная попытка входа"
        LOGIN_THROTTLED = "login_throttled", "Вход заблокирован ограничителем"
        USER_ACTIVITY = "user_activity", "Действие пользователя"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="playlist_bridge_security_events")
    username_snapshot = models.CharField(max_length=254, blank=True)
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    ip_address = models.CharField(max_length=45, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    http_method = models.CharField(max_length=10, blank=True)
    route_name = models.CharField(max_length=100, blank=True, db_index=True)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    referer_host = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "событие безопасности пользователя"
        verbose_name_plural = "события безопасности пользователей"

    def __str__(self):
        return f"{self.username_snapshot} · {self.get_event_type_display()} · {self.created_at:%Y-%m-%d %H:%M}"
