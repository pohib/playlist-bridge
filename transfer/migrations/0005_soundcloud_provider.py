from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0004_library_workspace")]

    operations = [
        migrations.AlterField(
            model_name="oauthcredential",
            name="provider",
            field=models.CharField(
                choices=[("vk", "VK"), ("spotify", "Spotify"), ("soundcloud", "SoundCloud")],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="libraryplaylist",
            name="provider",
            field=models.CharField(
                choices=[
                    ("vk", "ВКонтакте"),
                    ("spotify", "Spotify"),
                    ("soundcloud", "SoundCloud"),
                    ("youtube_music", "YouTube Music"),
                    ("apple_music", "Apple Music"),
                    ("manual", "Локальная коллекция"),
                ],
                default="manual",
                max_length=24,
            ),
        ),
    ]
