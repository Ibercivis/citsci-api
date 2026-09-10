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

    _deliver(log, subject, 'email/platform_notification.html', context, recipients, lang,
             text_body=_text_body(context))


def _deliver(log, subject, template, context, recipients, lang, text_body='', reply_to=None):
    """
    Renderiza y manda **un correo por destinatario**, no uno con todos en el To.

    Un informe de proyecto puede tener 37 administradores, varios de organizaciones distintas:
    meterlos a todos en el To seria ensenar 37 direcciones ajenas a cada uno. Y CCO tampoco:
    con copia oculta un rebote no dice que direccion fallo, y la reputacion de envio de SES se
    paga por rebote. Uno por persona es ademas lo que ya hace markers.tasks para las
    notificaciones de observacion.

    Cada uno lo recibe **en su idioma** (Profile.language), agrupando para renderizar una vez por
    idioma y no una por persona. `lang` pasa a ser solo el respaldo de quien no lo tenga puesto.

    Limitacion conocida: el asunto y el texto plano se construyen una sola vez, con el idioma de
    respaldo. Lo que cambia por destinatario es el HTML, que es el que se lee. Los nombres de
    proyecto ya vienen resueltos en el contexto.
    """
    log.subject = subject
    log.recipients = recipients

    enviados, fallos = [], []
    for idioma, grupo in _group_by_language(recipients, lang).items():
        try:
            with translation.override(idioma):
                cuerpo_html = render_to_string(template, {'subject': subject, **context})
        except Exception as exc:
            fallos.append(f'{grupo}: error al renderizar en {idioma}: {exc}')
            logger.error(f'Envio {log.event} {log.period_key} fallo al renderizar en {idioma}: {exc}')
            continue
        for recipient in grupo:
            try:
                message = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body or subject,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient],
                    reply_to=reply_to or [],
                )
                message.attach_alternative(cuerpo_html, 'text/html')
                message.send(fail_silently=False)
                enviados.append(recipient)
            except Exception as exc:
                # Un destinatario que falla no puede impedir que los demas reciban el correo.
                fallos.append(f'{recipient}: {exc}')
                logger.error(f'Envio {log.event} {log.period_key} fallo para {recipient}: {exc}')

    log.error = ' | '.join(fallos)
    if enviados:
        log.status = NotificationLog.STATUS_SENT
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'sent_at', 'error', 'subject', 'recipients'])
        logger.info(f'Envio {log.event} {log.period_key} enviado a {len(enviados)} '
                    f'destinatario(s){", con " + str(len(fallos)) + " fallo(s)" if fallos else ""}')
    else:
        log.status = NotificationLog.STATUS_FAILED
        log.save(update_fields=['status', 'error', 'subject', 'recipients'])
        raise RuntimeError(f'Ningun destinatario recibio {log.event} {log.period_key}: {log.error}')


def send_digest(period='fortnightly', lang='es'):
    """
    Resumen periodico. Lo llama el scheduler; el trabajo de verdad se puede lanzar tambien a mano
    con `manage.py send_stats_digest`, que es lo que lo hace testeable sin tocar Redis.
    """
    from stats.digest import DIGEST_EVENT, build_digest_context, digest_period_key

    context = build_digest_context(period, lang=lang)
    period_key = digest_period_key(context)
    subject = (f'[Geonity] Resumen {context["period_label"]} '
               f'({context["since"]} a {context["until"]})')

    log, created = NotificationLog.objects.get_or_create(
        event=DIGEST_EVENT, period_key=period_key, defaults={'subject': subject})
    if not created and log.status == NotificationLog.STATUS_SENT:
        logger.info(f'Resumen {period_key} ya enviado, no se repite')
        return

    recipients = list(settings.PLATFORM_NOTIFICATION_EMAILS)
    if not recipients:
        log.status = NotificationLog.STATUS_FAILED
        log.error = 'PLATFORM_NOTIFICATION_EMAILS esta vacio'
        log.save(update_fields=['status', 'error'])
        logger.warning(f'Resumen {period_key} sin destinatarios configurados')
        return

    text_body = _digest_text_body(context)
    _deliver(log, subject, 'email/platform_digest.html', context, recipients, lang,
             text_body=text_body)


def _digest_text_body(context):
    """Version en texto plano del resumen. Sin graficos, pero con las mismas cifras."""
    lines = [
        f'Resumen {context["period_label"]} de Geonity',
        f'Periodo: {context["since"]} a {context["until"]} ({context["days"]} dias)',
        '',
    ]
    for item in context['headline']:
        if item['delta_pct'] is None:
            lines.append(f'{item["label"]}: {item["value"]}')
        else:
            signo = '+' if item['delta_pct'] > 0 else ''
            lines.append(f'{item["label"]}: {item["value"]} '
                         f'({signo}{item["delta_pct"]}% vs {item["previous"]} del periodo anterior)')

    contributors = context['contributors']
    platform = context['platform']
    lines += [
        '',
        f'Contribuidores distintos: {contributors["total"]} '
        f'({contributors["registered"]} con cuenta, {contributors["anonymous"]} anonimos)',
        f'Plataforma: {platform["mobile"]} movil, {platform["web"]} web, '
        f'{platform["unknown"]} sin registrar',
        '',
        f'Totales: {context["total_projects"]} proyectos '
        f'({context["total_published"]} publicados, {context["active_30d"]} activos en 30 dias, '
        f'{context["abandoned"]} abandonados), {context["total_observations"]} observaciones '
        f'({context["anonymous_observations"]} anonimas), {context["total_users"]} usuarios.',
        '',
    ]
    if context.get('abandoned_projects'):
        lines.append('Proyectos publicados sin actividad:')
        for p in context['abandoned_projects']:
            cuanto = f'{p["days"]} dias sin observaciones' if p['days'] is not None else 'nunca ha recibido observaciones'
            lines.append(f'  - {p["name"]}: {cuanto}')
        lines.append('')
    lines.append('Evolucion de los ultimos meses:')
    for chart in context['charts']:
        serie = '  '.join(f'{bar["label"]} {bar["count"]}' for bar in chart['bars'])
        lines.append(f'  {chart["title"]}: {serie}')
    return '\n'.join(lines)


def send_project_digests(period='month', lang='es'):
    """
    Reparte el informe mensual por proyecto: encola un job por proyecto en vez de mandarlos todos
    aqui, para que un proyecto que falle no se lleve por delante a los demas.
    """
    import django_rq
    from project.models import Project
    from stats.project_digest import project_digest_kind, KIND_NONE

    queue = django_rq.get_queue('citisciapi')
    encolados = 0
    for project in Project.objects.filter(ended=False, email_monthly_stats=True).select_related('creator'):
        if project_digest_kind(project, period) is KIND_NONE:
            continue
        try:
            queue.enqueue('stats.tasks.send_project_digest', project.id, period, lang)
            encolados += 1
        except Exception as exc:
            logger.warning(f'No se pudo encolar el informe del proyecto {project.id}: {exc}')
    logger.info(f'Informes de proyecto encolados: {encolados}')
    return encolados


def send_project_digest(project_id, period='month', lang='es'):
    """Informe de un proyecto, o aviso de inactividad si esta publicado y parado."""
    from project.models import Project
    from stats.project_digest import (
        EVENT_INACTIVE, EVENT_REPORT, KIND_INACTIVE, KIND_NONE, KIND_REPORT,
        build_project_context, project_digest_kind, project_recipients,
    )

    try:
        project = Project.objects.select_related('creator').get(pk=project_id)
    except Project.DoesNotExist:
        logger.error(f'send_project_digest: el proyecto {project_id} no existe')
        return

    kind = project_digest_kind(project, period)
    if kind is KIND_NONE:
        logger.info(f'Proyecto {project_id}: no le toca correo este periodo')
        return

    context = build_project_context(project, period, lang=lang)
    if kind == KIND_REPORT:
        event = EVENT_REPORT
        period_key = f'project-{project.id}-digest-{context["until"]}'
        subject = f'[Geonity] {context["project_name"]}: resumen {context["period_label"]}'
        template = 'email/project_digest.html'
        reply_to = []
    else:
        event = EVENT_INACTIVE
        period_key = f'project-{project.id}-inactive-{context["until"]}'
        subject = f'[Geonity] {context["project_name"]} lleva un tiempo sin actividad'
        template = 'email/project_inactive.html'
        # Este correo invita a responder, asi que va a una direccion real y con otro pie.
        reply_to = [settings.PLATFORM_CONTACT_EMAIL] if settings.PLATFORM_CONTACT_EMAIL else []
        context['contact_email'] = settings.PLATFORM_CONTACT_EMAIL

    log, created = NotificationLog.objects.get_or_create(
        event=event, period_key=period_key, defaults={'subject': subject})
    if not created and log.status == NotificationLog.STATUS_SENT:
        logger.info(f'{event} {period_key} ya enviado, no se repite')
        return

    recipients = project_recipients(project)
    if not recipients:
        log.status = NotificationLog.STATUS_FAILED
        log.error = 'El proyecto no tiene ningun destinatario con email'
        log.save(update_fields=['status', 'error'])
        logger.warning(f'Proyecto {project_id} sin destinatarios con email')
        return

    _deliver(log, subject, template, context, recipients, lang,
             text_body=_project_text_body(kind, context), reply_to=reply_to)


def _project_text_body(kind, context):
    from stats.project_digest import KIND_REPORT

    if kind != KIND_REPORT:
        lines = [
            f'{context["project_name"]} no ha recibido observaciones en los ultimos '
            f'{context["days"]} dias.',
            '',
        ]
        if context.get('last_observation'):
            lines.append(f'Ultima observacion: {context["last_observation"]} '
                         f'({context["days_since_last"]} dias).')
        else:
            lines.append('El proyecto no ha recibido ninguna observacion todavia.')
        lines += [
            '',
            'Si quieres darle un empujon, escribenos respondiendo a este correo y te echamos una '
            f'mano ({context.get("contact_email", "")}).',
            'Y si el proyecto ya ha cumplido su ciclo, puedes marcarlo como terminado desde su '
            'pagina de edicion.',
            '',
            context['url'],
        ]
        return '\n'.join(lines)

    contributors = context['contributors']
    platform = context['platform']
    lines = [
        f'{context["project_name"]} - resumen {context["period_label"]}',
        f'Periodo: {context["since"]} a {context["until"]} ({context["days"]} dias)',
        '',
    ]
    if context['delta_pct'] is None:
        lines.append(f'Observaciones en el periodo: {context["observations"]}')
    else:
        signo = '+' if context['delta_pct'] > 0 else ''
        lines.append(f'Observaciones en el periodo: {context["observations"]} '
                     f'({signo}{context["delta_pct"]}% vs {context["previous_observations"]} del anterior)')
    lines += [
        f'Contribuidores: {contributors["total"]} '
        f'({contributors["new"]} nuevos, {contributors["recurring"]} repiten)',
        f'Plataforma: {platform["mobile"]} movil, {platform["web"]} web, {platform["unknown"]} sin registrar',
        f'Anonimas (QR): {context["anonymous"]}',
        '',
        f'Total historico del proyecto: {context["total_observations"]} observaciones '
        f'(desde {context["first_observation"]}).',
        '',
        'Evolucion: ' + '  '.join(f'{b["label"]} {b["count"]}' for b in context['bars']),
        '',
        context['url'],
    ]
    return '\n'.join(lines)


def _group_by_language(recipients, fallback):
    """
    {idioma: [direcciones]} segun Profile.language, con `fallback` para quien no lo tenga.

    Se busca por email porque los destinatarios del resumen de plataforma son cadenas de
    configuracion, no usuarios; los de un informe de proyecto si son usuarios y siempre casan.
    """
    from users.models import Profile

    fallback = fallback or settings.LANGUAGE_CODE
    idiomas = dict(
        Profile.objects
        .filter(user__email__in=recipients)
        .exclude(language='')
        .values_list('user__email', 'language')
    )
    validos = dict(settings.LANGUAGES)
    grupos = {}
    for recipient in recipients:
        idioma = idiomas.get(recipient, fallback)
        if idioma not in validos:
            idioma = fallback
        grupos.setdefault(idioma, []).append(recipient)
    return grupos
