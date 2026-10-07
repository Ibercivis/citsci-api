"""
GET /api/users/me/activity/ — actividad en los proyectos que el usuario crea o administra.

Qué es «actividad»: un hecho con fecha, hecho por una persona (o un participante anónimo), en un proyecto que el
usuario **crea o administra**. No incluye lo que el usuario hace en proyectos ajenos (eso es «Continuar participando»
y «Tu impacto» de Inicio).

No hay una tabla de eventos: el listado se compone al vuelo con tablas que ya existen. Lo que no se registra hoy
(proyecto editado, administrador aceptado o eliminado, observación borrada) no aparece. Las fuentes ruidosas
—observaciones, ediciones de datos de gestión y correos, que se hacen en bloque— se agrupan en una sola fila por
proyecto + persona + día, con un contador en `meta.count`.

Tipos: observation_created, participant_joined, project_created, project_published, project_unpublished,
project_ended, project_reopened, admin_invited, observation_admin_fields_edited, observation_email_sent.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from field_forms.translation import get_language_from_request, resolve_translation
from markers.models import Observation, ObservationEmailLog, ObservationFieldValue
from project.models import Project, ProjectInvitation, ProjectStatusLog

WINDOW_DAYS = 90
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
# Tope por fuente, por si un proyecto genera muchísimos eventos: se queda con los más recientes.
SOURCE_LIMIT = 1000

SCOPES = ('all', 'others', 'mine')
STATUS_EVENT_TYPES = {
    ProjectStatusLog.EVENT_CREATED: 'project_created',
    ProjectStatusLog.EVENT_PUBLISHED: 'project_published',
    ProjectStatusLog.EVENT_UNPUBLISHED: 'project_unpublished',
    ProjectStatusLog.EVENT_ENDED: 'project_ended',
    ProjectStatusLog.EVENT_REOPENED: 'project_reopened',
}


def _event(key, type_, at, actor_id, project_id, target=None, count=None, **meta):
    if count is not None:
        meta['count'] = count
    return {'key': key, 'type': type_, 'at': at, 'actor_id': actor_id, 'project_id': project_id,
            'target': target, 'meta': meta}


def _managed_project_ids(user):
    admin_ids = Project.administrators.through.objects.filter(user=user).values('project_id')
    return set(Project.objects.filter(Q(creator=user) | Q(id__in=admin_ids)).values_list('id', flat=True))


def collect_events(project_ids, since):
    """Eventos de esos proyectos desde `since`, sin ordenar ni filtrar por actor."""
    events = []
    if not project_ids:
        return events

    # Observaciones nuevas, agrupadas por proyecto + persona + día. Los anónimos (creator nulo) forman un grupo por día.
    observations = (
        Observation.objects.filter(field_form__project__in=project_ids, created_at__gte=since)
        .annotate(day=TruncDate('created_at'))
        .values('field_form__project', 'creator', 'day')
        .annotate(n=Count('id'), last=Max('created_at'), last_id=Max('id'))
        .order_by('-last')[:SOURCE_LIMIT]
    )
    for row in observations:
        project_id, actor_id = row['field_form__project'], row['creator']
        events.append(_event(
            f"observations:{project_id}:{actor_id or 0}:{row['day']}", 'observation_created', row['last'],
            actor_id, project_id, target={'observation_id': row['last_id']} if row['n'] == 1 else None, count=row['n'],
            anonymous=actor_id is None,
        ))

    # Nuevo participante: la primera observación de una persona registrada en el proyecto cae dentro de la ventana.
    # Los creadores y administradores del proyecto no cuentan como «participantes que se unen».
    managers = {}
    for project in Project.objects.filter(id__in=project_ids).values('id', 'creator'):
        managers[project['id']] = {project['creator']}
    for through in Project.administrators.through.objects.filter(project_id__in=project_ids).values('project_id', 'user_id'):
        managers[through['project_id']].add(through['user_id'])
    firsts = (
        Observation.objects.filter(field_form__project__in=project_ids, creator__isnull=False)
        .values('field_form__project', 'creator')
        .annotate(first=Min('created_at'))
        .filter(first__gte=since)
    )
    for row in firsts:
        project_id, actor_id = row['field_form__project'], row['creator']
        if actor_id in managers.get(project_id, ()):
            continue
        events.append(_event(f"joined:{project_id}:{actor_id}", 'participant_joined', row['first'], actor_id, project_id))

    # Cambios de estado del proyecto (se descartan las filas del backfill: su fecha es una estimación).
    for log in ProjectStatusLog.objects.filter(
        project__in=project_ids, at__gte=since, estimated=False,
    ).order_by('-at')[:SOURCE_LIMIT]:
        events.append(_event(f"status:{log.id}", STATUS_EVENT_TYPES[log.event], log.at, log.by_id, log.project_id))

    # Administradores invitados (sin e-mail del invitado en la respuesta).
    for invitation in ProjectInvitation.objects.filter(
        project__in=project_ids, created_at__gte=since,
    ).order_by('-created_at')[:SOURCE_LIMIT]:
        events.append(_event(
            f"invitation:{invitation.id}", 'admin_invited', invitation.created_at,
            invitation.invited_by_id, invitation.project_id, status=invitation.status,
        ))

    # Datos de gestión editados: se hacen en bloque, una fila por proyecto + persona + día.
    edits = (
        ObservationFieldValue.objects.filter(
            observation__field_form__project__in=project_ids, updated_at__gte=since, updated_by__isnull=False)
        .annotate(day=TruncDate('updated_at'))
        .values('observation__field_form__project', 'updated_by', 'day')
        .annotate(n=Count('observation', distinct=True), last=Max('updated_at'))
        .order_by('-last')[:SOURCE_LIMIT]
    )
    for row in edits:
        project_id, actor_id = row['observation__field_form__project'], row['updated_by']
        events.append(_event(
            f"edits:{project_id}:{actor_id}:{row['day']}", 'observation_admin_fields_edited', row['last'],
            actor_id, project_id, count=row['n'],
        ))

    # Correos a participantes (solo los enviados), también agrupados.
    emails = (
        ObservationEmailLog.objects.filter(
            observation__field_form__project__in=project_ids, created_at__gte=since,
            status=ObservationEmailLog.STATUS_SENT)
        .annotate(day=TruncDate('created_at'))
        .values('observation__field_form__project', 'sent_by', 'day')
        .annotate(n=Count('observation', distinct=True), last=Max('created_at'))
        .order_by('-last')[:SOURCE_LIMIT]
    )
    for row in emails:
        project_id, actor_id = row['observation__field_form__project'], row['sent_by']
        events.append(_event(
            f"emails:{project_id}:{actor_id or 0}:{row['day']}", 'observation_email_sent', row['last'],
            actor_id, project_id, count=row['n'],
        ))

    return events


class MyActivityView(APIView):
    """
    Actividad en los proyectos que el usuario crea o administra.

    Parámetros opcionales: `scope` = `all` (por defecto) | `others` | `mine`; `project` (id de uno de mis proyectos);
    `page`; `page_size` (por defecto 20, máx. 50). Ventana: últimos 90 días.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        lang = get_language_from_request(request)

        scope = request.query_params.get('scope', 'all')
        if scope not in SCOPES:
            return Response({'scope': [f"Valor no válido. Usa uno de: {', '.join(SCOPES)}."]},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            page_number = max(1, int(request.query_params.get('page', 1)))
            page_size = min(MAX_PAGE_SIZE, max(1, int(request.query_params.get('page_size', DEFAULT_PAGE_SIZE))))
            only_project = request.query_params.get('project')
            only_project = int(only_project) if only_project else None
        except ValueError:
            return Response({'detail': 'page, page_size y project deben ser enteros.'}, status=status.HTTP_400_BAD_REQUEST)

        project_ids = _managed_project_ids(user)
        if only_project is not None:
            # Un proyecto que no es mío no devuelve nada (y no se distingue de uno inexistente).
            project_ids = project_ids & {only_project}

        events = collect_events(project_ids, timezone.now() - timedelta(days=WINDOW_DAYS))
        if scope == 'mine':
            events = [e for e in events if e['actor_id'] == user.id]
        elif scope == 'others':
            events = [e for e in events if e['actor_id'] != user.id]
        events.sort(key=lambda e: (e['at'], e['key']), reverse=True)

        paginator = Paginator(events, page_size)
        try:
            page = paginator.page(page_number)
        except EmptyPage:
            page = paginator.page(paginator.num_pages) if paginator.count else None
        rows = list(page.object_list) if page else []

        # Nombres de personas y proyectos de la página, en dos consultas.
        actors = dict(User.objects.filter(id__in={e['actor_id'] for e in rows if e['actor_id']})
                      .values_list('id', 'username'))
        projects = {p.id: p for p in Project.objects.filter(id__in={e['project_id'] for e in rows})
                    .prefetch_related('covers')}

        def cover_url(project):
            cover = next(iter(project.covers.all()), None)
            return request.build_absolute_uri(cover.image.url) if cover and cover.image else None

        def page_url(number):
            query = request.query_params.copy()
            query['page'] = number
            return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")

        results = []
        for e in rows:
            project = projects[e['project_id']]
            actor = ({'id': e['actor_id'], 'name': actors.get(e['actor_id'], ''), 'is_me': e['actor_id'] == user.id}
                     if e['actor_id'] else None)
            results.append({
                'id': e['key'],
                'type': e['type'],
                'created_at': e['at'],
                'actor': actor,
                'project': {'id': project.id, 'name': resolve_translation(project.name, lang), 'cover_thumb': cover_url(project)},
                'target': e['target'],
                'meta': e['meta'],
            })

        return Response({
            'count': paginator.count,
            'next': page_url(page.next_page_number()) if page and page.has_next() else None,
            'previous': page_url(page.previous_page_number()) if page and page.has_previous() else None,
            'results': results,
        })
