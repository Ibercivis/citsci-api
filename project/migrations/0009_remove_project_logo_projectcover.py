# Generated by Django 4.1.5 on 2023-09-19 10:59

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0008_project_cover_project_logo'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='project',
            name='logo',
        ),
        migrations.CreateModel(
            name='ProjectCover',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(blank=True, null=True, upload_to='projects/covers/')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='covers', to='project.project')),
            ],
        ),
    ]
