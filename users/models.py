from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
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

    def __str__(self):
        return self.user.username
