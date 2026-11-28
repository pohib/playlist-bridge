from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transfer", "0019_merge_useripban_usereqpreset"),
    ]

    operations = [
        migrations.AlterField(
            model_name="useripban",
            name="ip_address",
            field=models.GenericIPAddressField(db_index=True),
        ),
    ]
