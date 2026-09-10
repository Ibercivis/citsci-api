"""
Calculo de metricas. Funciones puras: reciben querysets y devuelven dicts.

Aqui no se importa nada de DRF a proposito. Las tres vistas de estadisticas (plataforma, creador y
proyecto) y el email de resumen periodico llaman a estas mismas funciones con querysets distintos,
asi que los conteos se arreglan en un solo sitio.

Dos reglas que no son obvias y conviene no romper:

1. La actividad se mide con `Observation.created_at`, NUNCA con `Project.last_observation`. Este
   ultimo se alimenta de `Observation.timestamp`, que lo manda el cliente sin validar (ver
   markers/api/views.py, `request.data.get("timestamp")`): un movil con el reloj mal puesto dejaria
   un proyecto "activo" para siempre. `created_at` es auto_now_add, lo pone el servidor.

2. Nunca mezclar en un mismo `aggregate()` conteos que hagan JOIN (imagenes, audios) con conteos
   que no lo hagan: el JOIN duplica filas e infla los demas. Van en llamadas separadas.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from field_forms.translation import resolve_translation
from markers.models import Observation
from organizations.models import Organization
from project.models import Project, ProjectInvitation, ProjectMembership

ACTIVE_DAYS = 30
ABANDONED_DAYS = 90


def _last_observation_by_project(project_qs):
    """
    {project_id: fecha de la ultima observacion} en una sola query, con created_at de servidor.
    Solo aparecen los proyectos que tienen alguna observacion.
    """
    rows = (
        Observation.objects
        .filter(field_form__project__in=project_qs)
        .values('field_form__project_id')
        .annotate(last=Max('created_at'))
    )
    return {r['field_form__project_id']: r['last'] for r in rows}


def project_metrics(project_qs, now=None):
    now = now or timezone.now()
    active_cutoff = now - timedelta(days=ACTIVE_DAYS)
    abandoned_cutoff = now - timedelta(days=ABANDONED_DAYS)

    counts = project_qs.aggregate(
        total=Count('id'),
        published=Count('id', filter=Q(draft=False, ended=False)),
        draft=Count('id', filter=Q(draft=True)),
        ended=Count('id', filter=Q(ended=True)),
        private=Count('id', filter=Q(is_private=True)),
        anonymous_enabled=Count('id', filter=Q(anonymous_contribution=True)),
        public_map=Count('id', filter=Q(public_map=True)),
    )

    last_by_project = _last_observation_by_project(project_qs)
    published_ids = set(project_qs.filter(draft=False, ended=False).values_list('id', flat=True))

    active_ids = {pid for pid, last in last_by_project.items() if last >= active_cutoff}
    recent_ids = {pid for pid, last in last_by_project.items() if last >= abandoned_cutoff}

    counts['with_observations'] = len(last_by_project)
    # Se cuenta sobre TODOS los proyectos, borradores incluidos: con la contribucion anonima por QR
    # un borrador puede estar recogiendo datos activamente.
    counts['active_30d'] = len(active_ids)
    counts['active_30d_published'] = len(active_ids & published_ids)
    counts['abandoned'] = len(published_ids - recent_ids)
    return counts


def observation_metrics(observation_qs, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=ACTIVE_DAYS)

    counts = observation_qs.aggregate(
        total=Count('id'),
        last_30d=Count('id', filter=Q(created_at__gte=cutoff)),
        anonymous=Count('id', filter=Q(anonymous_id__isnull=False)),
    )
    platform = observation_qs.aggregate(
        mobile=Count('id', filter=Q(platform=Observation.PLATFORM_MOBILE)),
        web=Count('id', filter=Q(platform=Observation.PLATFORM_WEB)),
        unknown=Count('id', filter=Q(platform__isnull=True)),
    )
    # En su propia query: estos dos hacen JOIN y duplicarian filas de los conteos de arriba.
    media = observation_qs.aggregate(
        with_images=Count('id', filter=Q(images__isnull=False), distinct=True),
        with_audio=Count('id', filter=Q(audios__isnull=False), distinct=True),
    )

    counts['by_platform'] = platform
    counts.update(media)
    return counts


def user_metrics(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=ACTIVE_DAYS)

    counts = User.objects.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True)),
        new_30d=Count('id', filter=Q(date_joined__gte=cutoff)),
    )
    counts['with_observations'] = (
        Observation.objects.filter(creator__isnull=False).values('creator_id').distinct().count()
    )
    return counts


def organization_metrics():
    return {'total': Organization.objects.count()}


def engagement_metrics():
    return {
        'memberships': ProjectMembership.objects.count(),
        'invitations_pending': ProjectInvitation.objects.filter(status='pending').count(),
        'likes': Project.likes.through.objects.count(),
    }


def _period_starts(since, until, granularity):
    """Todos los inicios de periodo entre since y until, para rellenar los huecos sin datos."""
    starts = []
    if granularity == 'week':
        cursor = since - timedelta(days=since.weekday())
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        while cursor < until:
            starts.append(cursor)
            cursor = cursor + timedelta(days=7)
    else:
        cursor = since.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor < until:
            starts.append(cursor)
            cursor = (cursor + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return starts


def timeseries(queryset, field, since, until, granularity='month'):
    """
    Serie por periodo con los huecos rellenos a 0, y su acumulado.

    El acumulado arranca de lo que hubiera ANTES de `since` (una query extra), para que no parezca
    que la plataforma nacio el primer dia del rango pedido.
    """
    if since >= until:
        return [], []

    trunc = TruncWeek if granularity == 'week' else TruncMonth
    rows = (
        queryset
        .filter(**{f'{field}__gte': since, f'{field}__lt': until})
        .annotate(period=trunc(field))
        .values('period')
        .annotate(count=Count('id'))
        .order_by('period')
    )
    by_period = {r['period']: r['count'] for r in rows if r['period'] is not None}

    running = queryset.filter(**{f'{field}__lt': since}).count()
    series, cumulative = [], []
    for start in _period_starts(since, until, granularity):
        count = by_period.get(start, 0)
        running += count
        key = start.date().isoformat()
        series.append({'period': key, 'count': count})
        cumulative.append({'period': key, 'count': running})
    return series, cumulative


def top_projects(project_qs, lang='es', limit=10, since=None):
    """
    Con `since`, cuenta solo las observaciones a partir de esa fecha (para "actividad del periodo").

    El filtro va dentro del Count a proposito. Filtrar el queryset y anotar despues tambien
    funcionaria, porque Django reutiliza el JOIN, pero eso es un efecto sutil que se rompe si
    alguien reordena el codigo sin saberlo.
    """
    count_filter = Q(fieldform__observations__created_at__gte=since) if since else Q()
    rows = (
        project_qs
        .annotate(observations=Count('fieldform__observations', filter=count_filter))
        .filter(observations__gt=0)
        .order_by('-observations', 'id')
        .values('id', 'name', 'observations', 'draft', 'ended')[:limit]
    )
    return [
        {
            'id': r['id'],
            'name': resolve_translation(r['name'], lang),
            'observations': r['observations'],
            'published': not r['draft'] and not r['ended'],
        }
        for r in rows
    ]


def top_creators(project_qs, lang='es', limit=10):
    """
    Creadores de proyecto ordenados por observaciones recibidas en el conjunto de sus proyectos.
    No son los usuarios que mas observaciones envian: son los que llevan los proyectos mas activos.

    Se devuelve el username, nunca el email.
    """
    # Ojo: no se puede anotar como `observations`, que es el related_name de Observation.creator
    # en User y Django lo rechaza por colision con un campo del modelo.
    rows = (
        User.objects
        .filter(project__in=project_qs)
        .annotate(
            observations_received=Count('project__fieldform__observations'),
            projects_count=Count('project', distinct=True),
        )
        .filter(observations_received__gt=0)
        .order_by('-observations_received', 'id')
        .values('id', 'username', 'observations_received', 'projects_count')[:limit]
    )
    return [
        {
            'id': r['id'],
            'username': r['username'],
            'observations': r['observations_received'],
            'projects': r['projects_count'],
        }
        for r in rows
    ]


def contributor_metrics(observation_qs):
    """
    Cuantas personas distintas han contribuido. Los anonimos se cuentan por `anonymous_id`, que es
    lo mas cerca que se puede estar de "un navegador": no identifica a nadie y NO sale en la
    respuesta, solo su cardinalidad.
    """
    registered = observation_qs.filter(creator__isnull=False).values('creator_id').distinct().count()
    anonymous = observation_qs.filter(anonymous_id__isnull=False).values('anonymous_id').distinct().count()
    return {
        'registered': registered,
        'anonymous': anonymous,
        'total': registered + anonymous,
    }


def per_project_summary(project_qs, lang='es', now=None):
    """Una fila por proyecto, en una sola query. Nada de Project.contributions, que es N+1."""
    now = now or timezone.now()
    active_cutoff = now - timedelta(days=ACTIVE_DAYS)

    rows = (
        project_qs
        .annotate(
            observations_count=Count('fieldform__observations'),
            last_observation_at=Max('fieldform__observations__created_at'),
        )
        .order_by('-observations_count', 'id')
        .values('id', 'name', 'draft', 'ended', 'created_at', 'published_at',
                'observations_count', 'last_observation_at')
    )
    return [
        {
            'id': r['id'],
            'name': resolve_translation(r['name'], lang),
            'published': not r['draft'] and not r['ended'],
            'draft': r['draft'],
            'ended': r['ended'],
            'created_at': r['created_at'],
            'published_at': r['published_at'],
            'observations': r['observations_count'],
            'last_observation': r['last_observation_at'],
            'active_30d': bool(r['last_observation_at'] and r['last_observation_at'] >= active_cutoff),
        }
        for r in rows
    ]


def observation_span(observation_qs):
    """Primera y ultima observacion, por fecha de servidor."""
    span = observation_qs.aggregate(first=Min('created_at'), last=Max('created_at'))
    return {'first_observation': span['first'], 'last_observation': span['last']}


def abandoned_projects(project_qs, lang='es', limit=10, now=None):
    """
    Proyectos publicados sin actividad reciente, con nombre y cuantos dias llevan parados.

    Con el nombre delante el dato es accionable: "1 abandonado" no dice nada, "Flood2Now lleva 4
    meses parado" si. Los que nunca han recibido una observacion salen con days=None.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=ABANDONED_DAYS)

    rows = (
        project_qs
        .filter(draft=False, ended=False)
        .annotate(last_observation_at=Max('fieldform__observations__created_at'))
        .filter(Q(last_observation_at__lt=cutoff) | Q(last_observation_at__isnull=True))
        .order_by('last_observation_at')
        .values('id', 'name', 'last_observation_at')[:limit]
    )
    return [
        {
            'id': r['id'],
            'name': resolve_translation(r['name'], lang),
            'last_observation': r['last_observation_at'],
            'days': (now - r['last_observation_at']).days if r['last_observation_at'] else None,
        }
        for r in rows
    ]


def compare_periods(queryset, field, since, until):
    """
    Un numero del periodo con su comparacion contra el periodo anterior de la misma duracion.

    Un "114 observaciones" solo no dice nada; "114, un 57% menos que el periodo anterior" es lo que
    hace que alguien abra el panel. Si el periodo anterior es 0 no se inventa un porcentaje.
    """
    length = until - since
    value = queryset.filter(**{f'{field}__gte': since, f'{field}__lt': until}).count()
    previous = queryset.filter(**{f'{field}__gte': since - length, f'{field}__lt': since}).count()

    direction = 'flat'
    if value > previous:
        direction = 'up'
    elif value < previous:
        direction = 'down'

    return {
        'value': value,
        'previous': previous,
        'delta_pct': round((value - previous) * 100 / previous) if previous else None,
        'direction': direction,
    }


def contributor_timeseries(observation_qs, since, until, granularity='month'):
    """
    Personas distintas por periodo, separando las que estrenan de las que repiten.

    Es lo que la serie de observaciones no dice: 200 observaciones de 40 personas y 200 de una sola
    se ven igual mirando solo el volumen.

    Los anonimos cuentan por `anonymous_id`, que es lo mas cerca que se puede estar de "un
    navegador". Solo sale la cardinalidad, nunca el identificador.
    """
    if since >= until:
        return []

    trunc = TruncWeek if granularity == 'week' else TruncMonth

    # Distintos por periodo, en una query
    filas = (
        observation_qs
        .filter(created_at__gte=since, created_at__lt=until)
        .annotate(period=trunc('created_at'))
        .values('period')
        .annotate(
            registered=Count('creator_id', distinct=True),
            anonymous=Count('anonymous_id', distinct=True),
        )
    )
    por_periodo = {f['period']: (f['registered'], f['anonymous']) for f in filas if f['period']}

    # Primera aparicion de cada contribuidor en TODO el historico del queryset, para saber quien
    # estrena en cada periodo. Dos queries mas, una por tipo de contribuidor.
    estrenos = {}
    for campo in ('creator_id', 'anonymous_id'):
        primeras = (
            observation_qs
            .filter(**{f'{campo}__isnull': False})
            .values(campo)
            .annotate(primera=Min('created_at'))
            .values_list('primera', flat=True)
        )
        for momento in primeras:
            if since <= momento < until:
                cubo = _truncate(momento, granularity)
                estrenos[cubo] = estrenos.get(cubo, 0) + 1

    serie = []
    for inicio in _period_starts(since, until, granularity):
        registrados, anonimos = por_periodo.get(inicio, (0, 0))
        total = registrados + anonimos
        nuevos = min(estrenos.get(inicio, 0), total)
        serie.append({
            'period': inicio.date().isoformat(),
            'total': total,
            'registered': registrados,
            'anonymous': anonimos,
            'new': nuevos,
            'recurring': total - nuevos,
        })
    return serie


def platform_timeseries(observation_qs, since, until, granularity='month'):
    """Observaciones por periodo separadas por plataforma, para ver si la web despega o no."""
    if since >= until:
        return []

    trunc = TruncWeek if granularity == 'week' else TruncMonth
    filas = (
        observation_qs
        .filter(created_at__gte=since, created_at__lt=until)
        .annotate(period=trunc('created_at'))
        .values('period')
        .annotate(
            mobile=Count('id', filter=Q(platform=Observation.PLATFORM_MOBILE)),
            web=Count('id', filter=Q(platform=Observation.PLATFORM_WEB)),
            unknown=Count('id', filter=Q(platform__isnull=True)),
        )
    )
    por_periodo = {f['period']: f for f in filas if f['period']}
    serie = []
    for inicio in _period_starts(since, until, granularity):
        fila = por_periodo.get(inicio)
        serie.append({
            'period': inicio.date().isoformat(),
            'mobile': fila['mobile'] if fila else 0,
            'web': fila['web'] if fila else 0,
            'unknown': fila['unknown'] if fila else 0,
        })
    return serie


def _truncate(momento, granularity):
    """Inicio del cubo al que pertenece un instante, igual que hace TruncMonth/TruncWeek."""
    momento = momento.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == 'week':
        return momento - timedelta(days=momento.weekday())
    return momento.replace(day=1)
