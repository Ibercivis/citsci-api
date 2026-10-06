"""
Endpoints de solo lectura para las pantallas de Inicio y Gestionar del front React.

Son rutas nuevas: no sustituyen ni modifican ninguna ruta existente (la app móvil no las usa). Los contadores
se calculan con `annotate(Count(..., distinct=True))` en una sola consulta, no fila a fila.

  GET /api/users/me/impact/         «Tu impacto» de Inicio
  GET /api/users/me/pending-count/  contador de la campana (sustituye al sondeo doble de invitaciones)
  GET /api/home/continue/           «Continuar participando» de Inicio
  GET /api/manage/projects/         listado ligero de «Gestionar», con contadores por pestaña
"""
from datetime import timedelta

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, F, Max, Q
from django.db.models.functions import TruncWeek
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from field_forms.translation import get_language_from_request, resolve_translation
from markers.models import Observation
from organizations.models import Invitation as OrganizationInvitation
from project.api.serializers import OrganizationSummarySerializer
from project.models import Project, ProjectInvitation, ProjectMembership

CONTINUE_LIMIT = 20
MANAGE_DEFAULT_PAGE_SIZE = 20
MANAGE_MAX_PAGE_SIZE = 100


def _participating_project_ids(user):
    """Proyectos con alguna observación del usuario o con membresía (incluye los que crea o administra)."""
    from_observations = Observation.objects.filter(creator=user).values_list('field_form__project', flat=True)
    from_memberships = ProjectMembership.objects.filter(user=user).values_list('project', flat=True)
    return set(from_observations) | set(from_memberships)


def _first_cover_url(project, request):
    cover = next(iter(project.covers.all()), None)
    if not cover or not cover.image:
        return None
    return request.build_absolute_uri(cover.image.url)


def _latest(*moments):
    present = [m for m in moments if m is not None]
    return max(present) if present else None


# ─── GET /users/me/impact/ ──────────────────────────────────────────────────────

def _comparison(value, previous):
    """Mismo formato que `comparison` de las estadísticas: variación respecto al periodo anterior."""
    if previous == 0:
        return {'value': value, 'previous': previous, 'delta_pct': None, 'direction': 'up' if value > 0 else 'flat'}
    delta_pct = round((value - previous) * 100 / previous)
    direction = 'up' if value > previous else 'down' if value < previous else 'flat'
    return {'value': value, 'previous': previous, 'delta_pct': delta_pct, 'direction': direction}


def _month_start(moment):
    return timezone.localtime(moment).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _week_start(day):
    return day - timedelta(days=day.weekday())


def _streak_weeks(week_starts):
    """
    Semanas ISO consecutivas con alguna aportación. Si la semana en curso aún no tiene ninguna, la racha cuenta
    desde la anterior (no se rompe hasta que pase una semana entera sin aportar).
    """
    present = {w.date() for w in week_starts}
    cursor = _week_start(timezone.localdate())
    if cursor not in present:
        cursor -= timedelta(weeks=1)
    streak = 0
    while cursor in present:
        streak += 1
        cursor -= timedelta(weeks=1)
    return streak


class MyImpactView(APIView):
    """Métricas personales del usuario: observaciones, proyectos en los que participa, este mes y racha."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        mine = Observation.objects.filter(creator=user)
        now = timezone.now()
        this_month_start = _month_start(now)
        previous_month_start = _month_start(this_month_start - timedelta(days=1))

        this_month = mine.filter(timestamp__gte=this_month_start).count()
        previous_month = mine.filter(timestamp__gte=previous_month_start, timestamp__lt=this_month_start).count()

        week_starts = (
            mine.filter(timestamp__gte=now - timedelta(weeks=110))
            .annotate(week=TruncWeek('timestamp'))
            .values_list('week', flat=True)
            .distinct()
        )

        return Response({
            'observations': mine.count(),
            'projects_participating': len(_participating_project_ids(user)),
            'this_month': _comparison(this_month, previous_month),
            'last_observation': mine.aggregate(last=Max('timestamp'))['last'],
            'streak_weeks': _streak_weeks(week_starts),
        })


# ─── GET /users/me/pending-count/ ───────────────────────────────────────────────

class MyPendingCountView(APIView):
    """
    Invitaciones pendientes del usuario (de proyecto y de organización), contadas con los mismos filtros que
    `project/invitations/pending/` y `organization/invitations/pending/`, para que el número de la campana
    coincida con las listas.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        email = request.user.email
        projects = ProjectInvitation.objects.filter(email=email.lower(), status='pending').count()
        organizations = OrganizationInvitation.objects.filter(email=email, status='pending').count()
        return Response({
            'invitations': projects + organizations,
            'projects': projects,
            'organizations': organizations,
        })


# ─── GET /home/continue/ ────────────────────────────────────────────────────────

class HomeContinueView(APIView):
    """Proyectos donde el usuario ya participa (incluye los suyos), por su última observación. Máx. 20."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        lang = get_language_from_request(request)
        mine = Q(fieldform__observations__creator=user)

        projects = (
            Project.objects
            .filter(draft=False, id__in=_participating_project_ids(user))
            .prefetch_related('covers', 'organizations')
            .annotate(
                observations_total=Count('fieldform__observations', distinct=True),
                my_observations=Count('fieldform__observations', filter=mine, distinct=True),
                my_last=Max('fieldform__observations__timestamp', filter=mine),
            )
            .order_by(F('my_last').desc(nulls_last=True), '-updated_at')[:CONTINUE_LIMIT]
        )

        return Response([
            {
                'id': p.id,
                'name': resolve_translation(p.name, lang),
                'cover': _first_cover_url(p, request),
                'organizations': OrganizationSummarySerializer(
                    p.organizations.all(), many=True, context={'request': request}
                ).data,
                'observations_count': p.observations_total,
                'my_observations_count': p.my_observations,
                'last_observation': p.last_observation,
                'my_last_observation': p.my_last,
                'ended': p.ended,
            }
            for p in projects
        ])


# ─── GET /manage/projects/ ──────────────────────────────────────────────────────

class ManageProjectsView(APIView):
    """
    Proyectos que el usuario crea o administra, en versión ligera (sin formulario ni e-mails de administradores).

    Parámetros opcionales: `status` = `active` (por defecto) | `draft` | `ended`; `page`; `page_size` (máx. 100).
    `counts` trae siempre las tres cifras, para las pestañas, sea cual sea el `status` pedido.
    """
    permission_classes = [IsAuthenticated]

    STATUSES = ('active', 'draft', 'ended')

    def get(self, request):
        user = request.user
        lang = get_language_from_request(request)

        wanted = request.query_params.get('status', 'active')
        if wanted not in self.STATUSES:
            return Response({'status': [f"Valor no válido. Usa uno de: {', '.join(self.STATUSES)}."]},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            page_number = max(1, int(request.query_params.get('page', 1)))
            page_size = min(MANAGE_MAX_PAGE_SIZE, max(1, int(request.query_params.get('page_size', MANAGE_DEFAULT_PAGE_SIZE))))
        except ValueError:
            return Response({'detail': 'page y page_size deben ser enteros.'}, status=status.HTTP_400_BAD_REQUEST)

        admin_ids = Project.administrators.through.objects.filter(user=user).values('project_id')
        base = Project.objects.filter(Q(creator=user) | Q(id__in=admin_ids))

        # Los alias no pueden llamarse como un campo del modelo (`draft`, `ended`): Django los confundiría.
        totals = base.aggregate(
            n_active=Count('id', filter=Q(draft=False, ended=False)),
            n_draft=Count('id', filter=Q(draft=True)),
            n_ended=Count('id', filter=Q(draft=False, ended=True)),
        )
        counts = {'active': totals['n_active'], 'draft': totals['n_draft'], 'ended': totals['n_ended']}

        if wanted == 'draft':
            queryset = base.filter(draft=True).order_by('-updated_at')
        else:
            queryset = base.filter(draft=False, ended=(wanted == 'ended')).order_by(
                F('last_observation').desc(nulls_last=True), '-updated_at')

        queryset = queryset.prefetch_related('covers', 'organizations').annotate(
            observations_total=Count('fieldform__observations', distinct=True),
            registered_participants=Count('fieldform__observations__creator', distinct=True),
            anonymous_participants=Count('fieldform__observations__anonymous_id', distinct=True),
            last_status_change=Max('status_log__at'),
        )

        paginator = Paginator(queryset, page_size)
        try:
            page = paginator.page(page_number)
        except EmptyPage:
            page = paginator.page(paginator.num_pages) if paginator.count else None

        def page_url(number):
            if number is None:
                return None
            query = request.query_params.copy()
            query['page'] = number
            return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")

        results = []
        for p in (page.object_list if page else []):
            results.append({
                'id': p.id,
                'name': resolve_translation(p.name, lang),
                'cover': _first_cover_url(p, request),
                'organizations': OrganizationSummarySerializer(
                    p.organizations.all(), many=True, context={'request': request}
                ).data,
                'role': 'owner' if p.creator_id == user.id else 'admin',
                'draft': p.draft,
                'ended': p.ended,
                'published_at': p.published_at,
                # Personas distintas que han aportado: usuarios registrados + navegadores anónimos (QR).
                'participants_count': p.registered_participants + p.anonymous_participants,
                'observations_count': p.observations_total,
                'has_observations': p.observations_total > 0,
                'last_activity_at': _latest(p.last_observation, p.last_status_change),
            })

        return Response({
            'counts': counts,
            'count': paginator.count,
            'next': page_url(page.next_page_number()) if page and page.has_next() else None,
            'previous': page_url(page.previous_page_number()) if page and page.has_previous() else None,
            'results': results,
        })
