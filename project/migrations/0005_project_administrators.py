# Generated by Django 4.1.5 on 2023-05-04 10:30

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('project', '0004_project_organizations'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='administrators',
            field=models.ManyToManyField(related_name='admin_projects', to=settings.AUTH_USER_MODEL),
        ),
    ]
