from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from field_forms.translation import get_language_from_request, resolve_translation
from markers.api.views import _is_project_admin
from markers.models import Observation
from project.models import Project
from stats import metrics
from stats.api.throttles import StatsThrottle
from stats.models import NotificationLog

CACHE_TIMEOUT = 600  # 10 min. El TIMEOUT global de CACHES es de 24h, hay que pasarlo explicito.
# Version de la FORMA del payload. Va en la clave de cache: sin esto, tras desplegar un cambio de
# payload la API sigue sirviendo la forma antigua hasta 10 minutos, y el front recibe respuestas
# incoherentes segun le toque cache o no. Paso el 2026-09-10 al anadir `comparison`.
# SUBIRLA cada vez que se anadan o quiten claves del payload.
PAYLOAD_VERSION = 3
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
        cache_key = f'stats_platform_v{PAYLOAD_VERSION}_{since.date()}_{until.date()}_{granularity}_{lang}'
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
            'series_by_platform': metrics.platform_timeseries(
                observations, since, until, granularity),
            # Cada cifra con su variacion frente al periodo anterior de la misma duracion. Sin esto
            # el panel tiene que calcularla a mano o no mostrarla.
            'comparison': {
                'observations': metrics.compare_periods(observations, 'created_at', since, until),
                'users': metrics.compare_periods(User.objects.all(), 'date_joined', since, until),
                'projects_created': metrics.compare_periods(projects, 'created_at', since, until),
                'projects_published': metrics.compare_periods(
                    projects.filter(published_at__isnull=False), 'published_at', since, until),
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


class MyStatsView(GenericAPIView):
    """
    GET /api/stats/me/ — nivel de proyecto sobre los proyectos que el usuario crea o administra.

    No incluye los `top`: comparar proyectos entre si es exclusivo del nivel de plataforma.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [StatsThrottle]

    def get(self, request, *args, **kwargs):
        try:
            since, until, granularity, now = _parse_period(request)
        except InvalidParams as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        lang = get_language_from_request(request)
        cache_key = f'stats_me_v{PAYLOAD_VERSION}_{request.user.id}_{since.date()}_{until.date()}_{granularity}_{lang}'
        if request.query_params.get('refresh') not in ('1', 'true'):
            cached = cache.get(cache_key)
            if cached is not None:
                cached['cached'] = True
                return Response(cached)

        projects = Project.objects.filter(
            Q(creator=request.user) | Q(administrators=request.user)
        ).distinct()
        observations = Observation.objects.filter(field_form__project__in=projects)

        series, cumulative = metrics.timeseries(
            observations, 'created_at', since, until, granularity)

        payload = {
            'generated_at': now,
            'period': {
                'from': since.date().isoformat(),
                'to': until.date().isoformat(),
                'granularity': granularity,
            },
            'projects': metrics.project_metrics(projects, now=now),
            'observations': metrics.observation_metrics(observations, now=now),
            'contributors': metrics.contributor_metrics(
                observations.filter(created_at__gte=since, created_at__lt=until), observations, since),
            'series': {
                'observations': series,
                'observations_cumulative': cumulative,
                # Lo que la serie de observaciones no dice: 200 observaciones de 40 personas y 200
                # de una sola se ven igual mirando solo el volumen.
                'contributors': metrics.contributor_timeseries(
                    observations, since, until, granularity),
                'by_platform': metrics.platform_timeseries(
                    observations, since, until, granularity),
            },
            'comparison': {
                'observations': metrics.compare_periods(observations, 'created_at', since, until),
            },
            'per_project': metrics.per_project_summary(projects, lang=lang, now=now),
            'cached': False,
        }
        cache.set(cache_key, payload, CACHE_TIMEOUT)
        return Response(payload)


class ProjectStatsView(GenericAPIView):
    """
    GET /api/project/<pk>/stats/ — nivel de proyecto, para su creador y sus administradores.

    Los miembros (ProjectMembership) NO acceden: tienen el nivel publico, que ya expone el total de
    observaciones en el serializer de proyecto, y sus propias observaciones en /observations/my/.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [StatsThrottle]

    def get(self, request, pk, *args, **kwargs):
        project = get_object_or_404(Project, pk=pk)
        # Se reutiliza el helper que ya existe en markers en vez de escribir una tercera variante
        # de esta comprobacion: creador o administrador del proyecto.
        if not _is_project_admin(request.user, project):
            raise PermissionDenied(
                _('Solo el creador y los administradores del proyecto ven sus estadísticas.'))

        try:
            since, until, granularity, now = _parse_period(request)
        except InvalidParams as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        lang = get_language_from_request(request)
        cache_key = f'stats_project_v{PAYLOAD_VERSION}_{pk}_{since.date()}_{until.date()}_{granularity}_{lang}'
        if request.query_params.get('refresh') not in ('1', 'true'):
            cached = cache.get(cache_key)
            if cached is not None:
                cached['cached'] = True
                return Response(cached)

        observations = Observation.objects.filter(field_form__project=project)
        series, cumulative = metrics.timeseries(
            observations, 'created_at', since, until, granularity)

        payload = {
            'generated_at': now,
            'period': {
                'from': since.date().isoformat(),
                'to': until.date().isoformat(),
                'granularity': granularity,
            },
            'project': {
                'id': project.id,
                'name': resolve_translation(project.name, lang),
                'published': not project.draft and not project.ended,
                'draft': project.draft,
                'ended': project.ended,
                'created_at': project.created_at,
                'published_at': project.published_at,
            },
            'observations': metrics.observation_metrics(observations, now=now),
            'contributors': metrics.contributor_metrics(
                observations.filter(created_at__gte=since, created_at__lt=until), observations, since),
            'span': metrics.observation_span(observations),
            'series': {
                'observations': series,
                'observations_cumulative': cumulative,
                'contributors': metrics.contributor_timeseries(
                    observations, since, until, granularity),
                'by_platform': metrics.platform_timeseries(
                    observations, since, until, granularity),
            },
            'comparison': {
                'observations': metrics.compare_periods(observations, 'created_at', since, until),
            },
            'cached': False,
        }
        cache.set(cache_key, payload, CACHE_TIMEOUT)
        return Response(payload)
