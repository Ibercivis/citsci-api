"""
Construccion del resumen periodico.

La ventana la calcula esto, no el calendario: va desde el ultimo resumen enviado con exito hasta
ahora. Si el worker estuvo parado el dia 1, el envio del dia 15 cubre el hueco entero en vez de
dejar un agujero de datos que nadie va a notar. Solo si no hay ningun envio previo se cae al
tamano nominal del periodo.

Los graficos son barras hechas con celdas de tabla, no imagenes ni SVG: Gmail borra el SVG y muchos
clientes bloquean las imagenes por defecto, asi que un PNG adjunto se veria como un hueco hasta que
el lector pulse "mostrar imagenes". Las alturas en pixeles se calculan aqui, en Python, porque en
una plantilla de email no se puede hacer aritmetica.
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
CHART_MONTHS = 6
CHART_HEIGHT = 80
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
         'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


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


def _headline(label, queryset, field, since, until):
    """
    Un numero del periodo con su comparacion contra el periodo anterior de la misma duracion.

    Un "114 observaciones" solo no dice nada; "114, un 32% menos que la quincena anterior" es lo
    que hace que alguien abra el panel.
    """
    length = until - since
    value = queryset.filter(**{f'{field}__gte': since, f'{field}__lt': until}).count()
    previous = queryset.filter(
        **{f'{field}__gte': since - length, f'{field}__lt': since}).count()

    if previous:
        delta_pct = round((value - previous) * 100 / previous)
    else:
        delta_pct = None  # sin base de comparacion no se inventa un porcentaje
    direction = 'flat'
    if value > previous:
        direction = 'up'
    elif value < previous:
        direction = 'down'

    return {
        'label': label,
        'value': value,
        'previous': previous,
        'delta_pct': delta_pct,
        'direction': direction,
    }


def _bars(series):
    """Convierte una serie mensual en barras con altura en pixeles, escaladas al maximo."""
    top = max((point['count'] for point in series), default=0)
    bars = []
    for point in series:
        year, month, _ = point['period'].split('-')
        if top:
            # minimo 2px cuando hay algo, para que un mes flojo no parezca vacio
            height = max(2, round(point['count'] * CHART_HEIGHT / top))
        else:
            height = 1
        bars.append({
            'label': MESES[int(month) - 1],
            'year': year,
            'count': point['count'],
            'height': height if point['count'] else 1,
        })
    return bars


def build_digest_context(period, now=None, lang='es'):
    since, until = digest_window(period, now=now)
    label, _ = PERIODS.get(period, PERIODS['fortnightly'])

    projects = Project.objects.all()
    observations = Observation.objects.all()
    users = User.objects.all()

    project_totals = metrics.project_metrics(projects, now=until)
    observation_totals = metrics.observation_metrics(observations, now=until)
    period_observations = observations.filter(created_at__gte=since, created_at__lt=until)
    contributors = metrics.contributor_metrics(period_observations)
    # Del periodo, no historico: esta seccion del correo habla de la quincena, y mezclar un
    # acumulado de dos anos con contribuidores de 15 dias se lee mal.
    period_platform = metrics.observation_metrics(period_observations, now=until)['by_platform']

    headline = [
        _headline('observaciones nuevas', observations, 'created_at', since, until),
        _headline('usuarios nuevos', users, 'date_joined', since, until),
        _headline('proyectos nuevos', projects, 'created_at', since, until),
        _headline('proyectos publicados', projects.filter(published_at__isnull=False),
                  'published_at', since, until),
    ]

    # Exactamente CHART_MONTHS cubos: se arranca el dia 1 del mes (CHART_MONTHS-1) meses atras.
    # Con `until - 30*6 dias` salian 7 barras y la primera era un mes a medias, o sea una caida
    # falsa al principio de la serie.
    first_month = until.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(CHART_MONTHS - 1):
        first_month = (first_month - timedelta(days=1)).replace(day=1)
    chart_since = first_month
    charts = []
    for title, queryset, field in (
        ('Observaciones', observations, 'created_at'),
        ('Usuarios nuevos', users, 'date_joined'),
        ('Proyectos creados', projects, 'created_at'),
    ):
        series, _ = metrics.timeseries(queryset, field, chart_since, until, 'month')
        charts.append({'title': title, 'bars': _bars(series)})

    return {
        'period': period,
        'period_label': label,
        # El correo dice el rango EXACTO que cubre: "quincenal" son los dias 1 y 15, o sea periodos
        # de entre 13 y 16 dias, y ademas la ventana se estira si se perdio un envio.
        'since': since.date().isoformat(),
        'until': until.date().isoformat(),
        'days': (until - since).days,
        'headline': headline,
        'charts': charts,
        'chart_months': CHART_MONTHS,
        'contributors': contributors,
        'platform': period_platform,
        'platform_all_time': observation_totals['by_platform'],
        'anonymous_observations': observation_totals['anonymous'],
        'total_projects': project_totals['total'],
        'total_published': project_totals['published'],
        'active_30d': project_totals['active_30d'],
        'abandoned': project_totals['abandoned'],
        'total_observations': observation_totals['total'],
        'total_users': users.count(),
        'top_projects': metrics.top_projects(projects, lang=lang, limit=5, since=since),
        # Compatibilidad con el texto plano y con quien lea el contexto por su cuenta
        'new_observations': headline[0]['value'],
        'new_users': headline[1]['value'],
        'new_projects': headline[2]['value'],
        'published_projects': headline[3]['value'],
    }


def digest_period_key(context):
    """Una clave por ventana. Con el unique de NotificationLog, no salen dos correos del mismo periodo."""
    return f'{DIGEST_EVENT}-{context["until"]}'
