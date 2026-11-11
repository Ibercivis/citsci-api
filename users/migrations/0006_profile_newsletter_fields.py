from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_alter_profile_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='newsletter_accepted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='newsletter_revoked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
