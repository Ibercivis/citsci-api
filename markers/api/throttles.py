from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class AnonymousFormThrottle(AnonRateThrottle):
    """Lectura de la landing anónima del QR. Por IP."""
    scope = 'anon_form'


class AnonymousSubmitThrottle(AnonRateThrottle):
    """Envío de observaciones anónimas. Por IP."""
    scope = 'anon_submit'


class AnonymousIdSubmitThrottle(SimpleRateThrottle):
    """
    Envío de observaciones anónimas, por navegador (cabecera X-Anonymous-Id).
    Complementa al throttle por IP: varios móviles tras el mismo NAT no se pisan,
    y un mismo navegador cambiando de red sigue limitado.
    """
    scope = 'anon_submit_id'

    def get_cache_key(self, request, view):
        ident = (request.headers.get('X-Anonymous-Id') or '').strip()
        if not ident:
            return None  # sin cabecera la vista ya devuelve 400
        return self.cache_format % {'scope': self.scope, 'ident': ident}
