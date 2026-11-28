from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transfer", "0022_providerintegrationevent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="providerintegrationevent",
            name="provider",
            field=models.CharField(
                choices=[
                    ("transfer", "Перенос"),
                    ("spotify", "Spotify"),
                    ("vk", "VK"),
                    ("soundcloud", "SoundCloud"),
                    ("deezer", "Deezer"),
                    ("itunes", "Apple Music / iTunes"),
                    ("youtube_music", "YouTube Music"),
                    ("system", "Система"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
