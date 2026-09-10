"""
Registro de eventos de plataforma y encolado del aviso por email.

La idempotencia sale de `NotificationLog(event, period_key)`, que es unico. Para los eventos de
proyecto el `period_key` es **el id de la fila de ProjectStatusLog** que lo origina: un reintento de
rq no duplica el correo, y una segunda publicacion si manda el suyo porque es otra fila. Sin ese
ancla habria que inventarse una clave por numero de publicacion, que es donde salen los bugs.

Todo lo de aqui va envuelto en try/except: un fallo registrando o encolando un aviso no puede
tumbar la peticion que crea o edita un proyecto.
"""
import logging

import django_rq
from django.conf import settings
from django.utils import timezone

from field_forms.translation import resolve_translation
from project.models import ProjectStatusLog

logger = logging.getLogger('geonity')

EVENT_PROJECT_CREATED = 'project-created'
EVENT_PROJECT_PUBLISHED = 'project-published'
EVENT_PROJECT_REPUBLISHED = 'project-republished'
EVENT_PROJECT_UNPUBLISHED = 'project-unpublished'
EVENT_PROJECT_ENDED = 'project-ended'
EVENT_PROJECT_REOPENED = 'project-reopened'
EVENT_ORGANIZATION_CREATED = 'organization-created'
EVENT_PROJECT_MILESTONE = 'project-milestone'

MILESTONES = (1, 10, 100, 1000)


def _enqueue(event, period_key, context, lang):
    try:
        queue = django_rq.get_queue('citisciapi')
        queue.enqueue('stats.tasks.send_platform_notification', event, period_key, context, lang)
    except Exception as exc:
        logger.warning(f'No se pudo encolar el aviso {event} {period_key}: {exc}')


def _project_context(project, lang):
    name = resolve_translation(project.name, lang)
    return {
        'project_id': project.id,
        'project_name': name,
        'creator': project.creator.username if project.creator_id else '',
        'created_at': project.created_at.isoformat() if project.created_at else '',
        'published_at': project.published_at.isoformat() if project.published_at else '',
        'draft': project.draft,
        'ended': project.ended,
        'url': f'{settings.BASE_URL.rstrip("/")}/project/{project.id}',
    }


def record_project_created(project, by=None, lang='es'):
    try:
        log = ProjectStatusLog.objects.create(
            project=project, event=ProjectStatusLog.EVENT_CREATED, by=by)
    except Exception as exc:
        logger.warning(f'No se pudo registrar la creacion del proyecto {project.id}: {exc}')
        return None
    context = _project_context(project, lang)
    context['event_label'] = 'creado'
    _enqueue(EVENT_PROJECT_CREATED, f'project-status-{log.id}', context, lang)
    return log


def record_project_state_change(project, *, was_draft, was_ended, by=None, lang='es'):
    """
    Traduce el cambio de `draft`/`ended` a filas de historico y avisos.

    `published_at` es la PRIMERA publicacion y no se toca despues: si un proyecto vuelve a borrador
    y se publica otra vez, el evento es "republicado" y published_at sigue apuntando a la original.
    """
    changes = []

    if was_draft and not project.draft:
        first_publication = project.published_at is None
        if first_publication:
            project.published_at = timezone.now()
            project.save(update_fields=['published_at'])
        changes.append((
            ProjectStatusLog.EVENT_PUBLISHED,
            EVENT_PROJECT_PUBLISHED if first_publication else EVENT_PROJECT_REPUBLISHED,
            'publicado' if first_publication else 'republicado',
        ))
    elif not was_draft and project.draft:
        changes.append((ProjectStatusLog.EVENT_UNPUBLISHED, EVENT_PROJECT_UNPUBLISHED, 'despublicado'))

    if not was_ended and project.ended:
        changes.append((ProjectStatusLog.EVENT_ENDED, EVENT_PROJECT_ENDED, 'finalizado'))
    elif was_ended and not project.ended:
        changes.append((ProjectStatusLog.EVENT_REOPENED, EVENT_PROJECT_REOPENED, 'reabierto'))

    logs = []
    for log_event, mail_event, label in changes:
        try:
            log = ProjectStatusLog.objects.create(project=project, event=log_event, by=by)
        except Exception as exc:
            logger.warning(f'No se pudo registrar {log_event} del proyecto {project.id}: {exc}')
            continue
        context = _project_context(project, lang)
        context['event_label'] = label
        _enqueue(mail_event, f'project-status-{log.id}', context, lang)
        logs.append(log)
    return logs


def record_organization_created(organization, lang='es'):
    context = {
        'organization_id': organization.id,
        'organization_name': organization.principalName,
        'creator': organization.creator.username if organization.creator_id else '',
        'event_label': 'creada',
        'url': f'{settings.BASE_URL.rstrip("/")}/organization/{organization.id}',
    }
    _enqueue(EVENT_ORGANIZATION_CREATED, f'organization-{organization.id}', context, lang)


def record_observation_milestone(project, observation_count, lang='es'):
    """Se llama con el total de observaciones del proyecto; solo avisa en los hitos."""
    if observation_count not in MILESTONES:
        return
    context = _project_context(project, lang)
    context['event_label'] = f'ha alcanzado {observation_count} observaciones'
    context['milestone'] = observation_count
    _enqueue(EVENT_PROJECT_MILESTONE, f'project-{project.id}-milestone-{observation_count}',
             context, lang)
