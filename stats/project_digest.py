"""
Informe mensual por proyecto, para su creador y administradores.

Dos correos distintos segun el caso, decididos en `project_digest_kind()`:

- **Informe**: el proyecto ha recibido observaciones en el periodo. Sus numeros, su evolucion y
  quien contribuye.
- **Aviso de inactividad**: el proyecto esta PUBLICADO y no ha recibido nada. Ofrece ayuda para
  dinamizarlo o marcarlo como terminado, y responde a una direccion real.

Un borrador sin actividad no recibe nada: no es un proyecto abandonado, es uno que todavia no ha
salido. En produccion hay 24 borradores sin actividad frente a 1 publicado; mandarles el aviso seria
ruido del que acaba marcado como spam.
"""
from datetime import timedelta

from django.db.models import Min
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from markers.models import Observation
from stats import metrics
from stats.digest import CHART_MONTHS, PERIODS, _bars
from stats.models import NotificationLog

KIND_REPORT = 'report'
KIND_INACTIVE = 'inactive'
KIND_NONE = None

EVENT_REPORT = 'project-digest'
EVENT_INACTIVE = 'project-inactive'

# Tope de avisos seguidos a un proyecto parado. Despues, silencio hasta que vuelva a haber
# actividad: repetirlo cada mes durante anos es acoso, y el spam se paga en reputacion de SES.
MAX_CONSECUTIVE_INACTIVE = 3


def project_window(period, now=None):
    now = now or timezone.now()
    _label, nominal_days = PERIODS.get(period, PERIODS['month'])
    return now - timedelta(days=nominal_days), now


def project_recipients(project):
    emails = []
    if project.creator_id and project.creator.email:
        emails.append(project.creator.email)
    for admin in project.administrators.all():
        if admin.email and admin.email not in emails:
            emails.append(admin.email)
    return emails


def _consecutive_inactive_notices(project):
    """Cuantos avisos seguidos lleva, sin ningun informe de por medio."""
    last_report = (
        NotificationLog.objects
        .filter(event=EVENT_REPORT, period_key__startswith=f'project-{project.id}-digest-')
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    avisos = NotificationLog.objects.filter(
        event=EVENT_INACTIVE,
        period_key__startswith=f'project-{project.id}-inactive-',
        status=NotificationLog.STATUS_SENT,
    )
    if last_report:
        avisos = avisos.filter(created_at__gt=last_report)
    return avisos.count()


def project_digest_kind(project, period='month', now=None):
    """Que correo toca, si es que toca alguno."""
    if project.ended or not project.email_monthly_stats:
        return KIND_NONE

    since, until = project_window(period, now=now)
    hay_actividad = Observation.objects.filter(
        field_form__project=project, created_at__gte=since, created_at__lt=until).exists()

    if hay_actividad:
        return KIND_REPORT
    if project.draft:
        return KIND_NONE
    if _consecutive_inactive_notices(project) >= MAX_CONSECUTIVE_INACTIVE:
        return KIND_NONE
    return KIND_INACTIVE


def build_project_context(project, period='month', now=None, lang='es'):
    since, until = project_window(period, now=now)
    label = PERIODS.get(period, PERIODS['month'])[0]

    observations = Observation.objects.filter(field_form__project=project)
    del_periodo = observations.filter(created_at__gte=since, created_at__lt=until)

    # La misma comparativa que expone la API, no una segunda formula del mismo porcentaje.
    comparativa = metrics.compare_periods(observations, 'created_at', since, until)

    chart_from = until.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _mes in range(CHART_MONTHS - 1):
        chart_from = (chart_from - timedelta(days=1)).replace(day=1)
    serie, _acumulada = metrics.timeseries(observations, 'created_at', chart_from, until, 'month')

    span = metrics.observation_span(observations)
    ultima = span['last_observation']

    return {
        'project_id': project.id,
        'project_name': metrics.resolve_translation(project.name, lang),
        'period_label': label,
        'since': since.date().isoformat(),
        'until': until.date().isoformat(),
        'days': (until - since).days,
        'observations': comparativa['value'],
        'previous_observations': comparativa['previous'],
        'delta_pct': comparativa['delta_pct'],
        'direction': comparativa['direction'],
        'total_observations': observations.count(),
        'platform': metrics.observation_metrics(del_periodo, now=until)['by_platform'],
        'contributors': metrics.contributor_metrics(del_periodo, observations, since),
        'anonymous': del_periodo.filter(anonymous_id__isnull=False).count(),
        'bars': _bars(serie),
        'chart_months': CHART_MONTHS,
        'first_observation': span['first_observation'].date().isoformat() if span['first_observation'] else '',
        'last_observation': ultima.date().isoformat() if ultima else '',
        'days_since_last': (until - ultima).days if ultima else None,
        'published': not project.draft and not project.ended,
        'url': f'https://geonity.ibercivis.es/project/{project.id}',
    }
