from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfer", "0008_transfer_target_playlist")]

    operations = [
        migrations.AddField(
            model_name="librarytrack",
            name="cover_url",
            field=models.URLField(blank=True, max_length=2048),
        ),
    ]
