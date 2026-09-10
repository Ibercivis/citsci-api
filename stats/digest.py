"""
Construccion del resumen periodico.

La ventana la calcula esto, no el calendario: va desde el ultimo resumen enviado con exito hasta
ahora. Si el worker estuvo parado el dia 1, el envio del dia 15 cubre el hueco entero en vez de
dejar un agujero de datos que nadie va a notar. Solo si no hay ningun envio previo se cae al
tamano nominal del periodo.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from markers.models import Observation
from project.models import Project
from stats import metrics
from stats.models import NotificationLog

PERIODS = {
    'fortnightly': ('quincenal', 15),
    'month': ('mensual', 30),
}
DIGEST_EVENT = 'digest'


def digest_window(period, now=None):
    now = now or timezone.now()
    _, nominal_days = PERIODS.get(period, PERIODS['fortnightly'])
    last = (
        NotificationLog.objects
        .filter(event=DIGEST_EVENT, status=NotificationLog.STATUS_SENT, sent_at__isnull=False)
        .order_by('-sent_at')
        .values_list('sent_at', flat=True)
        .first()
    )
    since = last or (now - timedelta(days=nominal_days))
    return since, now


def build_digest_context(period, now=None, lang='es'):
    since, until = digest_window(period, now=now)
    label, _ = PERIODS.get(period, PERIODS['fortnightly'])

    projects = Project.objects.all()
    observations = Observation.objects.all()

    new_projects = projects.filter(created_at__gte=since, created_at__lt=until)
    published = projects.filter(published_at__gte=since, published_at__lt=until)
    new_observations = observations.filter(created_at__gte=since, created_at__lt=until)
    new_users = User.objects.filter(date_joined__gte=since, date_joined__lt=until)

    project_totals = metrics.project_metrics(projects, now=until)
    observation_totals = metrics.observation_metrics(observations, now=until)

    return {
        'period': period,
        'period_label': label,
        # El correo dice el rango EXACTO que cubre: "quincenal" son los dias 1 y 15, o sea periodos
        # de entre 13 y 16 dias, y ademas la ventana se estira si se perdio un envio.
        'since': since.date().isoformat(),
        'until': until.date().isoformat(),
        'days': (until - since).days,
        'new_projects': new_projects.count(),
        'published_projects': published.count(),
        'new_observations': new_observations.count(),
        'new_users': new_users.count(),
        'total_projects': project_totals['total'],
        'total_published': project_totals['published'],
        'active_30d': project_totals['active_30d'],
        'total_observations': observation_totals['total'],
        'total_users': User.objects.count(),
        'top_projects': metrics.top_projects(projects, lang=lang, limit=5, since=since),
    }


def digest_period_key(context):
    """Una clave por ventana. Con el unique de NotificationLog, no salen dos correos del mismo periodo."""
    return f'{DIGEST_EVENT}-{context["until"]}'
