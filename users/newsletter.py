"""Baja de la newsletter por enlace, sin iniciar sesion.

El enlace lleva el id del usuario firmado con SECRET_KEY: no se guarda nada en base de datos y no
caduca a proposito, porque la baja de un correo de hace un año tiene que seguir funcionando.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.urls import reverse

SALT = 'users.newsletter.unsubscribe'


def make_unsubscribe_token(user):
    return signing.dumps(user.pk, salt=SALT)


def user_from_unsubscribe_token(token):
    """El usuario del token, o None si el token no vale o el usuario ya no existe."""
    try:
        pk = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
    return User.objects.select_related('profile').filter(pk=pk).first()


def unsubscribe_url(user):
    path = reverse('newsletter-unsubscribe', args=[make_unsubscribe_token(user)])
    return f'{settings.BASE_URL.rstrip("/")}{path}'


def unsubscribe_headers(user):
    """Cabeceras de baja en un clic (RFC 8058), las que Gmail pide a los envios masivos."""
    return {
        'List-Unsubscribe': f'<{unsubscribe_url(user)}>',
        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    }
