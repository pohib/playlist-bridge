import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transfer", "0021_useraccountban"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderIntegrationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[
                    ("transfer", "Перенос"),
                    ("spotify", "Spotify"),
                    ("vk", "VK"),
                    ("soundcloud", "SoundCloud"),
                    ("system", "Система"),
                ], db_index=True, max_length=16)),
                ("operation", models.CharField(blank=True, max_length=80)),
                ("category", models.CharField(choices=[
                    ("auth", "Авторизация"),
                    ("rate_limit", "Ограничение запросов"),
                    ("network", "Сеть / тайм-аут"),
                    ("provider", "Ошибка провайдера"),
                    ("validation", "Валидация"),
                    ("worker", "Фоновая задача"),
                    ("unknown", "Не классифицировано"),
                ], db_index=True, max_length=20)),
                ("severity", models.CharField(choices=[
                    ("info", "Информация"),
                    ("warning", "Предупреждение"),
                    ("error", "Ошибка"),
                ], default="error", max_length=10)),
                ("message", models.CharField(max_length=500)),
                ("status_code", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("transfer_job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="integration_events", to="transfer.transferjob")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="playlist_bridge_integration_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "событие интеграции",
                "verbose_name_plural": "события интеграций",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="providerintegrationevent",
            index=models.Index(fields=["provider", "created_at"], name="prov_event_provider_date"),
        ),
        migrations.AddIndex(
            model_name="providerintegrationevent",
            index=models.Index(fields=["category", "created_at"], name="prov_event_category_date"),
        ),
    ]
