from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('markers', '0012_observationaudio'),
    ]

    operations = [
        migrations.AddField(
            model_name='observation',
            name='anonymous_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='observation',
            name='anonymous_source',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
