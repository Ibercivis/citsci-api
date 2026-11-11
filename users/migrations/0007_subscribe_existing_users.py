from django.db import migrations
from django.utils import timezone


def subscribe_everyone(apps, schema_editor):
    """
    Suscribe a la newsletter a todos los usuarios que existen al desplegar. Decision de producto:
    la casilla del alta llega despues que ellos, y sin esto la lista nacia vacia.

    Ojo al leer el dato: para estos perfiles `newsletter_accepted_at` es la fecha de esta migracion,
    no la de un consentimiento dado por el usuario. Quien se registre despues sigue siendo opt-in.
    """
    Profile = apps.get_model('users', 'Profile')
    Profile.objects.filter(newsletter_accepted_at__isnull=True).update(newsletter_accepted_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_profile_newsletter_fields'),
    ]

    operations = [
        migrations.RunPython(subscribe_everyone, migrations.RunPython.noop),
    ]
