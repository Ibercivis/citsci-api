from rest_framework.throttling import UserRateThrottle


class StatsThrottle(UserRateThrottle):
    """
    Las estadisticas son las queries mas caras de la API. DEFAULT_THROTTLE_CLASSES sigue vacio a
    proposito (no queremos limitar el resto), asi que el limite se declara aqui, vista a vista.
    """
    scope = 'stats'
