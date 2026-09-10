"""
Envio de los avisos de plataforma. Se ejecuta en el worker de rq (`citisciapi`).
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation

from stats.models import NotificationLog

logger = logging.getLogger('geonity')

SUBJECTS = {
    'project-created': 'Nuevo proyecto: {project_name}',
    'project-published': 'Proyecto publicado: {project_name}',
    'project-republished': 'Proyecto republicado: {project_name}',
    'project-unpublished': 'Proyecto despublicado: {project_name}',
    'project-ended': 'Proyecto finalizado: {project_name}',
    'project-reopened': 'Proyecto reabierto: {project_name}',
    'project-milestone': '{project_name}: {milestone} observaciones',
    'organization-created': 'Nueva organizacion: {organization_name}',
}


def _subject(event, context):
    template = SUBJECTS.get(event, '{event}')
    try:
        return '[Geonity] ' + template.format(event=event, **context)
    except KeyError:
        return f'[Geonity] {event}'


TEXT_LABELS = (
    ('project_name', 'Proyecto'),
    ('organization_name', 'Organizacion'),
    ('project_id', 'Id de proyecto'),
    ('organization_id', 'Id de organizacion'),
    ('creator', 'Creado por'),
    ('created_at', 'Fecha de creacion'),
    ('published_at', 'Primera publicacion'),
    ('milestone', 'Observaciones'),
    ('url', 'Enlace'),
)


def _text_body(context):
    """Version en texto plano legible, no un volcado del diccionario."""
    lines = []
    label = context.get('event_label')
    if label:
        lines.append(f'Aviso de plataforma: {label}.')
        lines.append('')
    for key, caption in TEXT_LABELS:
        value = context.get(key)
        if value not in (None, '', False):
            lines.append(f'{caption}: {value}')
    return '\n'.join(lines)


def send_platform_notification(event, period_key, context, lang='es'):
    """
    Manda un aviso a PLATFORM_NOTIFICATION_EMAILS, una sola vez por (event, period_key).

    La unicidad de NotificationLog es lo que hace esto idempotente: si rq reintenta el job, o
    alguien lo relanza a mano, el correo no sale dos veces.
    """
    subject = _subject(event, context)
    log, created = NotificationLog.objects.get_or_create(
        event=event,
        period_key=period_key,
        defaults={'subject': subject},
    )
    if not created and log.status == NotificationLog.STATUS_SENT:
        logger.info(f'Aviso {event} {period_key} ya enviado, no se repite')
        return

    recipients = list(settings.PLATFORM_NOTIFICATION_EMAILS)
    if not recipients:
        log.status = NotificationLog.STATUS_FAILED
        log.error = 'PLATFORM_NOTIFICATION_EMAILS esta vacio'
        log.save(update_fields=['status', 'error'])
        logger.warning(f'Aviso {event} {period_key} sin destinatarios configurados')
        return

    log.subject = subject
    log.recipients = recipients

    try:
        with translation.override(lang):
            html_body = render_to_string('email/platform_notification.html', {
                'subject': subject,
                'event': event,
                **context,
            })
        text_body = _text_body(context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)
    except Exception as exc:
        log.status = NotificationLog.STATUS_FAILED
        log.error = str(exc)
        log.save(update_fields=['status', 'error', 'subject', 'recipients'])
        logger.error(f'Aviso {event} {period_key} fallo: {exc}')
        raise

    log.status = NotificationLog.STATUS_SENT
    log.sent_at = timezone.now()
    log.error = ''
    log.save(update_fields=['status', 'sent_at', 'error', 'subject', 'recipients'])
    logger.info(f'Aviso {event} {period_key} enviado a {recipients}')
