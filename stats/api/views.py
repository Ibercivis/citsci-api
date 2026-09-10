from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from field_forms.translation import get_language_from_request
from markers.models import Observation
from project.models import Project
from stats import metrics
from stats.api.throttles import StatsThrottle
from stats.models import NotificationLog

CACHE_TIMEOUT = 600  # 10 min. El TIMEOUT global de CACHES es de 24h, hay que pasarlo explicito.
DEFAULT_MONTHS = 12
GRANULARITIES = ('month', 'week')


class InvalidParams(Exception):
    pass


def _parse_period(request):
    """
    ?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=month|week

    Por defecto, los ultimos 12 meses hasta ahora. `to` es exclusivo.
    """
    granularity = request.query_params.get('granularity', 'month')
    if granularity not in GRANULARITIES:
        raise InvalidParams(f"granularity debe ser uno de {', '.join(GRANULARITIES)}")

    now = timezone.now()
    until = now
    raw_to = request.query_params.get('to')
    if raw_to:
        parsed = parse_date(raw_to)
        if not parsed:
            raise InvalidParams("'to' debe tener formato YYYY-MM-DD")
        until = timezone.make_aware(timezone.datetime.combine(parsed, timezone.datetime.min.time()))

    since = until - timedelta(days=30 * DEFAULT_MONTHS)
    raw_from = request.query_params.get('from')
    if raw_from:
        parsed = parse_date(raw_from)
        if not parsed:
            raise InvalidParams("'from' debe tener formato YYYY-MM-DD")
        since = timezone.make_aware(timezone.datetime.combine(parsed, timezone.datetime.min.time()))

    if since > until:
        raise InvalidParams("'from' no puede ser posterior a 'to'")
    return since, until, granularity, now


class PlatformStatsView(GenericAPIView):
    """
    GET /api/stats/platform/ — metricas globales. Solo is_staff.

    Es el unico nivel que compara proyectos entre si (los `top`): esa informacion no baja a los
    endpoints de creador ni de proyecto.
    """
    permission_classes = [IsAdminUser]
    throttle_classes = [StatsThrottle]

    def get(self, request, *args, **kwargs):
        try:
            since, until, granularity, now = _parse_period(request)
        except InvalidParams as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        lang = get_language_from_request(request)
        cache_key = f'stats_platform_{since.date()}_{until.date()}_{granularity}_{lang}'
        if request.query_params.get('refresh') not in ('1', 'true'):
            cached = cache.get(cache_key)
            if cached is not None:
                cached['cached'] = True
                return Response(cached)

        projects = Project.objects.all()
        observations = Observation.objects.all()

        projects_series, projects_cumulative = metrics.timeseries(
            Project.objects.filter(published_at__isnull=False), 'published_at', since, until, granularity)
        created_series, created_cumulative = metrics.timeseries(
            projects, 'created_at', since, until, granularity)
        observations_series, observations_cumulative = metrics.timeseries(
            observations, 'created_at', since, until, granularity)
        users_series, users_cumulative = metrics.timeseries(
            User.objects.all(), 'date_joined', since, until, granularity)

        last_digest = (
            NotificationLog.objects
            .filter(event='digest', status=NotificationLog.STATUS_SENT)
            .order_by('-sent_at')
            .values_list('sent_at', flat=True)
            .first()
        )

        payload = {
            'generated_at': now,
            'period': {
                'from': since.date().isoformat(),
                'to': until.date().isoformat(),
                'granularity': granularity,
            },
            'projects': metrics.project_metrics(projects, now=now),
            'observations': metrics.observation_metrics(observations, now=now),
            'users': metrics.user_metrics(now=now),
            'organizations': metrics.organization_metrics(),
            'engagement': metrics.engagement_metrics(),
            'series': {
                'projects_created': created_series,
                'projects_created_cumulative': created_cumulative,
                # "publicados" son PRIMERAS publicaciones: published_at no se reescribe si un
                # proyecto vuelve a borrador y se publica otra vez.
                'projects_published': projects_series,
                'projects_published_cumulative': projects_cumulative,
                'observations': observations_series,
                'observations_cumulative': observations_cumulative,
                'users': users_series,
                'users_cumulative': users_cumulative,
            },
            'top': {
                'projects_by_observations': metrics.top_projects(projects, lang=lang),
                'creators_by_observations': metrics.top_creators(projects, lang=lang),
            },
            'last_digest_sent_at': last_digest,
            'cached': False,
        }
        cache.set(cache_key, payload, CACHE_TIMEOUT)
        return Response(payload)
