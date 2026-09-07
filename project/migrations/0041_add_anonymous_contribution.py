import uuid

from django.db import migrations, models


def populate_anonymous_tokens(apps, schema_editor):
    """Cada proyecto existente necesita su propio UUID antes de poder poner unique=True."""
    Project = apps.get_model('project', 'Project')
    for pk in Project.objects.filter(anonymous_token__isnull=True).values_list('pk', flat=True).iterator():
        Project.objects.filter(pk=pk).update(anonymous_token=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0040_add_show_post_message_to_project'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='anonymous_contribution',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='project',
            name='anonymous_token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_anonymous_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='project',
            name='anonymous_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
