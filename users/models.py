from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django_countries.fields import CountryField 

# Create your models here.

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    biography = models.TextField(blank=True, null=True)
    visibility = models.BooleanField(default=True)
    country = CountryField()  # Empleamos la librería `django-countries`.
    # Idioma preferido para los correos. Los avisos programados no tienen peticion de la que sacar
    # el Accept-Language, y los de evento usaban el idioma de QUIEN DISPARA la accion, que no tiene
    # nada que ver con el de quien lee. Vacio = se cae a LANGUAGE_CODE.
    # No se deduce de `country`: 738 de 783 perfiles lo tienen vacio, no sirve de nada.
    language = models.CharField(max_length=10, choices=settings.LANGUAGES, blank=True, default='')
    cover = models.ImageField(upload_to='users/covers/', null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, null=True, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_version = models.CharField(max_length=20, null=True, blank=True)
    # Consentimiento para recibir novedades de Geonity (newsletter). Es opt-in: vacio = nunca lo ha
    # aceptado. Se guardan las dos fechas y no un booleano porque la fecha es la prueba del
    # consentimiento, y la baja no debe borrar cuando se dio. Esta suscrito quien tiene aceptacion y
    # ninguna baja posterior (ver `newsletter_subscribed`). No afecta a los correos transaccionales.
    newsletter_accepted_at = models.DateTimeField(null=True, blank=True)
    newsletter_revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def newsletter_subscribed(self):
        if self.newsletter_accepted_at is None:
            return False
        return self.newsletter_revoked_at is None or self.newsletter_revoked_at < self.newsletter_accepted_at

    def set_newsletter(self, subscribed):
        """Alta o baja. Idempotente: repetir el estado actual no mueve las fechas."""
        if subscribed == self.newsletter_subscribed:
            return
        campo = 'newsletter_accepted_at' if subscribed else 'newsletter_revoked_at'
        setattr(self, campo, timezone.now())
        # update_fields: hay un post_save de User que guarda el perfil entero desde una instancia
        # que puede estar vieja; aqui se toca solo la columna que cambia.
        self.save(update_fields=[campo])

    @staticmethod
    def newsletter_subscribed_q(prefix=''):
        """Q equivalente a `newsletter_subscribed`, para filtrar en base de datos."""
        accepted = f'{prefix}newsletter_accepted_at'
        revoked = f'{prefix}newsletter_revoked_at'
        return models.Q(**{f'{accepted}__isnull': False}) & (
            models.Q(**{f'{revoked}__isnull': True}) | models.Q(**{f'{revoked}__lt': models.F(accepted)})
        )

    def __str__(self):
        return self.user.username
