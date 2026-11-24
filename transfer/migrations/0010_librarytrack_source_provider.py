from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0009_librarytrack_cover_url")]

    operations = [
        migrations.AddField(
            model_name="librarytrack",
            name="source_provider",
            field=models.CharField(
                blank=True,
                choices=[
                    ("vk", "ВКонтакте"), ("spotify", "Spotify"),
                    ("soundcloud", "SoundCloud"), ("youtube_music", "YouTube Music"),
                    ("apple_music", "Apple Music"), ("manual", "Локальная коллекция"),
                ],
                max_length=24,
            ),
        ),
    ]
