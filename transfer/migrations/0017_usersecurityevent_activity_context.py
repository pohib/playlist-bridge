from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0016_usersecurityevent")]

    operations = [
        migrations.AlterField(
            model_name="usersecurityevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("login_succeeded", "Успешный вход"),
                    ("login_failed", "Неудачная попытка входа"),
                    ("login_throttled", "Вход заблокирован ограничителем"),
                    ("user_activity", "Действие пользователя"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AddField(model_name="usersecurityevent", name="http_method", field=models.CharField(blank=True, max_length=10)),
        migrations.AddField(model_name="usersecurityevent", name="route_name", field=models.CharField(blank=True, db_index=True, max_length=100)),
        migrations.AddField(model_name="usersecurityevent", name="response_status", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="usersecurityevent", name="request_id", field=models.UUIDField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="usersecurityevent", name="duration_ms", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="usersecurityevent", name="object_type", field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name="usersecurityevent", name="object_id", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="usersecurityevent", name="referer_host", field=models.CharField(blank=True, max_length=255)),
    ]
