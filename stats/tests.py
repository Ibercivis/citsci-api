from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from field_forms.models import FieldForm
from markers.models import Observation
from project.models import Project
from stats import metrics
from stats.models import NotificationLog
from stats.digest import build_digest_context, digest_window
from stats.tasks import send_digest, send_platform_notification

# La cache por defecto es el Redis de produccion: los tests usan locmem para no escribir ahi ni
# arrastrar estado entre ejecuciones. Vale tambien para el throttle, que se apoya en la cache.
TEST_CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


class NotificationLogTests(TestCase):
    def test_event_and_period_key_are_unique_together(self):
        """
        Es la garantia de idempotencia de todos los emails de plataforma: un reintento de rq o un
        disparo manual del comando no pueden mandar dos veces el mismo correo.
        """
        NotificationLog.objects.create(event='digest', period_key='digest-2026-09')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NotificationLog.objects.create(event='digest', period_key='digest-2026-09')

    def test_same_period_key_for_a_different_event_is_allowed(self):
        NotificationLog.objects.create(event='digest', period_key='2026-09')
        NotificationLog.objects.create(event='project-published', period_key='2026-09')
        self.assertEqual(NotificationLog.objects.count(), 2)

    def test_defaults(self):
        log = NotificationLog.objects.create(event='digest', period_key='digest-2026-10')
        self.assertEqual(log.status, NotificationLog.STATUS_PENDING)
        self.assertEqual(log.recipients, [])
        self.assertEqual(log.error, '')
        self.assertIsNone(log.sent_at)


def _make_project(creator, name, *, draft=False, ended=False, **kwargs):
    project = Project.objects.create(
        creator=creator, name=name, description={'default': name}, draft=draft, ended=ended, **kwargs
    )
    FieldForm.objects.create(project=project)
    return project


def _make_observation(project, *, created_at, creator=None, anonymous_id=None, platform='mobile'):
    from django.contrib.gis.geos import Point

    obs = Observation.objects.create(
        creator=creator,
        field_form=project.fieldform,
        timestamp=created_at,
        geoposition=Point(-0.88, 41.65, srid=4326),
        data=[],
        platform=platform,
        anonymous_id=anonymous_id,
    )
    # created_at es auto_now_add: para simular actividad antigua hay que escribirlo despues.
    Observation.objects.filter(pk=obs.pk).update(created_at=created_at)
    obs.refresh_from_db()
    return obs


class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.creator = User.objects.create_user(username='creador', email='c@example.com')
        cls.activo = _make_project(cls.creator, 'Activo')
        cls.parado = _make_project(cls.creator, 'Parado')
        cls.borrador = _make_project(cls.creator, 'Borrador', draft=True)
        cls.terminado = _make_project(cls.creator, 'Terminado', ended=True)

        _make_observation(cls.activo, created_at=cls.now - timedelta(days=2))
        _make_observation(cls.activo, created_at=cls.now - timedelta(days=5),
                          anonymous_id='11111111-1111-1111-1111-111111111111', platform='web')
        _make_observation(cls.parado, created_at=cls.now - timedelta(days=200))
        # El borrador tambien recoge datos: contribucion anonima por QR.
        _make_observation(cls.borrador, created_at=cls.now - timedelta(days=1),
                          anonymous_id='22222222-2222-2222-2222-222222222222', platform='web')

    def test_project_counts(self):
        m = metrics.project_metrics(Project.objects.all(), now=self.now)
        self.assertEqual(m['total'], 4)
        self.assertEqual(m['published'], 2)      # Activo y Parado
        self.assertEqual(m['draft'], 1)
        self.assertEqual(m['ended'], 1)
        self.assertEqual(m['with_observations'], 3)

    def test_active_30d_includes_drafts_but_active_published_does_not(self):
        m = metrics.project_metrics(Project.objects.all(), now=self.now)
        self.assertEqual(m['active_30d'], 2)             # Activo + Borrador
        self.assertEqual(m['active_30d_published'], 1)   # solo Activo

    def test_abandoned_is_published_without_recent_activity(self):
        m = metrics.project_metrics(Project.objects.all(), now=self.now)
        self.assertEqual(m['abandoned'], 1)              # Parado: publicado y ultima obs hace 200 dias

    def test_activity_uses_created_at_not_the_client_timestamp(self):
        """
        Una observacion con timestamp en el futuro (reloj del movil mal puesto) no puede hacer que
        un proyecto parado parezca activo: la actividad se mide con created_at, que pone el servidor.
        """
        obs = Observation.objects.filter(field_form__project=self.parado).first()
        obs.timestamp = self.now + timedelta(days=3650)
        obs.save(update_fields=['timestamp'])
        m = metrics.project_metrics(Project.objects.all(), now=self.now)
        self.assertEqual(m['active_30d'], 2)
        self.assertEqual(m['abandoned'], 1)

    def test_observation_counts_are_not_inflated_by_the_image_join(self):
        m = metrics.observation_metrics(Observation.objects.all(), now=self.now)
        self.assertEqual(m['total'], 4)
        self.assertEqual(m['anonymous'], 2)
        self.assertEqual(m['by_platform'], {'mobile': 2, 'web': 2, 'unknown': 0})
        self.assertEqual(m['with_images'], 0)
        self.assertEqual(m['with_audio'], 0)

    def test_timeseries_fills_gaps_and_accumulates_from_before(self):
        since = self.now - timedelta(days=90)
        series, cumulative = metrics.timeseries(
            Observation.objects.all(), 'created_at', since, self.now, 'month')
        self.assertGreaterEqual(len(series), 3)
        self.assertEqual([p['period'] for p in series], [p['period'] for p in cumulative])
        # La observacion de hace 200 dias queda fuera del rango pero cuenta en el acumulado.
        self.assertEqual(cumulative[0]['count'] - series[0]['count'], 1)
        self.assertEqual(cumulative[-1]['count'], 4)

    def test_timeseries_of_an_empty_range_is_empty(self):
        series, cumulative = metrics.timeseries(
            Observation.objects.all(), 'created_at', self.now, self.now, 'month')
        self.assertEqual(series, [])
        self.assertEqual(cumulative, [])

    def test_top_projects_orders_by_observations(self):
        top = metrics.top_projects(Project.objects.all())
        self.assertEqual(top[0]['name'], 'Activo')
        self.assertEqual(top[0]['observations'], 2)
        self.assertNotIn('Terminado', [p['name'] for p in top])  # sin observaciones, fuera

    def test_top_creators_never_exposes_the_email(self):
        top = metrics.top_creators(Project.objects.all())
        self.assertEqual(top[0]['username'], 'creador')
        self.assertEqual(top[0]['observations'], 4)
        self.assertNotIn('email', top[0])


@override_settings(CACHES=TEST_CACHES)
class PlatformStatsViewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('stats_platform')
        cls.staff = User.objects.create_user(username='staff', email='s@example.com', is_staff=True)
        cls.normal = User.objects.create_user(username='pepe', email='p@example.com')
        cls.staff_token = Token.objects.create(user=cls.staff)
        cls.normal_token = Token.objects.create(user=cls.normal)
        project = _make_project(cls.staff, 'Uno')
        _make_observation(project, created_at=timezone.now() - timedelta(days=1),
                          anonymous_id='33333333-3333-3333-3333-333333333333')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_normal_user_gets_403(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.normal_token.key}')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_staff_gets_the_payload(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for block in ('projects', 'observations', 'users', 'organizations', 'engagement',
                      'series', 'top', 'period'):
            self.assertIn(block, response.data)
        self.assertEqual(response.data['projects']['total'], 1)
        self.assertEqual(response.data['observations']['anonymous'], 1)

    def test_anonymous_id_is_never_exposed(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')
        body = self.client.get(self.url).content.decode()
        self.assertNotIn('33333333-3333-3333-3333-333333333333', body)
        self.assertNotIn('anonymous_id', body)

    def test_invalid_params_return_400(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')
        self.assertEqual(self.client.get(self.url, {'granularity': 'siglo'}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'from': 'ayer'}).status_code, 400)
        self.assertEqual(
            self.client.get(self.url, {'from': '2026-05-01', 'to': '2026-01-01'}).status_code, 400)

    def test_second_call_is_served_from_cache_and_refresh_skips_it(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')
        self.assertFalse(self.client.get(self.url).data['cached'])
        self.assertTrue(self.client.get(self.url).data['cached'])
        self.assertFalse(self.client.get(self.url, {'refresh': '1'}).data['cached'])

    def test_query_count_is_bounded(self):
        """
        Blindaje contra el N+1 de Project.contributions, que hace un count() por proyecto. Si esto
        salta, alguien ha metido un bucle de queries en metrics.py.
        """
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')
        with self.assertNumQueries(24):
            self.client.get(self.url)


@override_settings(CACHES=TEST_CACHES)
class ProjectLevelStatsTests(APITestCase):
    """
    Los tres niveles de visibilidad: publico (ya existia), proyecto (creador + administradores) y
    plataforma (is_staff). Aqui se fija el del medio.
    """

    @classmethod
    def setUpTestData(cls):
        from project.models import ProjectMembership

        cls.creator = User.objects.create_user(username='duena', email='d@example.com')
        cls.admin = User.objects.create_user(username='admina', email='a@example.com')
        cls.member = User.objects.create_user(username='miembro', email='m@example.com')
        cls.stranger = User.objects.create_user(username='ajena', email='x@example.com')
        cls.other_creator = User.objects.create_user(username='otra', email='o@example.com')

        cls.project = _make_project(cls.creator, 'Mío')
        cls.project.administrators.add(cls.admin)
        ProjectMembership.objects.create(project=cls.project, user=cls.member)

        cls.other = _make_project(cls.other_creator, 'Ajeno')

        _make_observation(cls.project, created_at=timezone.now() - timedelta(days=1),
                          creator=cls.member)
        _make_observation(cls.project, created_at=timezone.now() - timedelta(days=3),
                          anonymous_id='44444444-4444-4444-4444-444444444444', platform='web')
        _make_observation(cls.other, created_at=timezone.now() - timedelta(days=1),
                          creator=cls.other_creator)

        cls.tokens = {u.username: Token.objects.create(user=u).key
                      for u in (cls.creator, cls.admin, cls.member, cls.stranger, cls.other_creator)}
        cls.project_url = reverse('stats_project', args=[cls.project.id])
        cls.me_url = reverse('stats_me')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _as(self, username):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.tokens[username]}')

    # --- /api/project/<pk>/stats/ ---

    def test_anonymous_gets_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.project_url).status_code, 401)

    def test_creator_and_admin_get_200(self):
        for username in ('duena', 'admina'):
            self._as(username)
            self.assertEqual(self.client.get(self.project_url).status_code, 200, username)

    def test_member_is_denied(self):
        """Decidido: los miembros NO ven el nivel de proyecto, solo el público y lo suyo."""
        self._as('miembro')
        self.assertEqual(self.client.get(self.project_url).status_code, 403)

    def test_stranger_is_denied(self):
        self._as('ajena')
        self.assertEqual(self.client.get(self.project_url).status_code, 403)

    def test_project_payload(self):
        self._as('duena')
        data = self.client.get(self.project_url).data
        self.assertEqual(data['project']['id'], self.project.id)
        self.assertEqual(data['observations']['total'], 2)
        self.assertEqual(data['contributors'], {'registered': 1, 'anonymous': 1, 'total': 2})
        self.assertIsNotNone(data['span']['first_observation'])
        # Los rankings entre proyectos son exclusivos del nivel de plataforma.
        self.assertNotIn('top', data)

    def test_project_stats_never_expose_the_anonymous_id(self):
        self._as('duena')
        body = self.client.get(self.project_url).content.decode()
        self.assertNotIn('44444444-4444-4444-4444-444444444444', body)
        self.assertNotIn('anonymous_id', body)

    def test_404_for_a_project_that_does_not_exist(self):
        self._as('duena')
        self.assertEqual(self.client.get(reverse('stats_project', args=[999999])).status_code, 404)

    # --- /api/stats/me/ ---

    def test_me_only_counts_my_projects(self):
        self._as('duena')
        data = self.client.get(self.me_url).data
        self.assertEqual(data['projects']['total'], 1)
        self.assertEqual(data['observations']['total'], 2)
        self.assertEqual([p['id'] for p in data['per_project']], [self.project.id])

    def test_me_includes_projects_i_administrate(self):
        self._as('admina')
        data = self.client.get(self.me_url).data
        self.assertEqual([p['id'] for p in data['per_project']], [self.project.id])

    def test_me_is_empty_for_someone_without_projects(self):
        self._as('ajena')
        data = self.client.get(self.me_url).data
        self.assertEqual(data['projects']['total'], 0)
        self.assertEqual(data['per_project'], [])

    def test_me_does_not_leak_other_peoples_projects(self):
        self._as('duena')
        body = self.client.get(self.me_url).content.decode()
        self.assertNotIn('Ajeno', body)

    def test_me_has_no_cross_project_ranking(self):
        self._as('duena')
        self.assertNotIn('top', self.client.get(self.me_url).data)

    def test_per_project_marks_activity(self):
        self._as('duena')
        row = self.client.get(self.me_url).data['per_project'][0]
        self.assertTrue(row['active_30d'])
        self.assertEqual(row['observations'], 2)
        self.assertTrue(row['published'])


@override_settings(CACHES=TEST_CACHES)
class ProjectEventTests(APITestCase):
    """
    El ciclo de vida de un proyecto y los avisos que genera. `draft` es reversible, asi que lo que
    se fija aqui es que published_at NO se reescriba y que cada transicion sea su propia fila.
    """

    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(username='autora', email='a@example.com')
        cls.token = Token.objects.create(user=cls.creator)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        self.project = _make_project(self.creator, 'Ciclo', draft=True)
        # El serializer exige mas de 10 observaciones para dejar publicar un proyecto.
        for _ in range(11):
            _make_observation(self.project, created_at=timezone.now(), creator=self.creator)
        self.url = f'/api/project/{self.project.id}/'

    def _patch(self, **payload):
        with patch('stats.events._enqueue') as enqueue:
            response = self.client.patch(self.url, payload, format='json')
        self.project.refresh_from_db()
        return response, enqueue

    def test_publishing_records_one_event_and_sets_published_at(self):
        response, enqueue = self._patch(draft=False)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.project.published_at)
        self.assertEqual(self.project.status_log.filter(event='published').count(), 1)
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(enqueue.call_args[0][0], 'project-published')

    def test_saving_an_already_published_project_records_nothing(self):
        self._patch(draft=False)
        _, enqueue = self._patch(name='Ciclo renombrado')
        self.assertEqual(enqueue.call_count, 0)
        self.assertEqual(self.project.status_log.filter(event='published').count(), 1)

    def test_unpublishing_records_its_own_event(self):
        self._patch(draft=False)
        _, enqueue = self._patch(draft=True)
        self.assertEqual(enqueue.call_args[0][0], 'project-unpublished')
        self.assertEqual(self.project.status_log.filter(event='unpublished').count(), 1)

    def test_full_cycle_keeps_the_first_published_at(self):
        """draft -> publicado -> draft -> publicado: 3 eventos, y published_at el de la primera."""
        self._patch(draft=False)
        first_published_at = self.project.published_at
        self._patch(draft=True)
        _, enqueue = self._patch(draft=False)

        self.assertEqual(self.project.published_at, first_published_at)
        self.assertEqual(enqueue.call_args[0][0], 'project-republished')
        events = list(self.project.status_log.order_by('at', 'id').values_list('event', flat=True))
        self.assertEqual(events, ['published', 'unpublished', 'published'])

    def test_each_transition_has_its_own_idempotency_key(self):
        self._patch(draft=False)
        self._patch(draft=True)
        _, enqueue = self._patch(draft=False)
        keys = [
            call[0][1] for call in enqueue.call_args_list
        ]
        self.assertEqual(len(keys), len(set(keys)), 'las claves de idempotencia no pueden repetirse')

    def test_ending_and_reopening(self):
        _, enqueue = self._patch(ended=True)
        self.assertEqual(enqueue.call_args[0][0], 'project-ended')
        _, enqueue = self._patch(ended=False)
        self.assertEqual(enqueue.call_args[0][0], 'project-reopened')


@override_settings(
    CACHES=TEST_CACHES,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PLATFORM_NOTIFICATION_EMAILS=['uno@example.com', 'dos@example.com'],
)
class SendPlatformNotificationTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def _context(self):
        return {'project_id': 7, 'project_name': 'Proyecto', 'creator': 'autora',
                'created_at': '2026-09-10T10:00:00', 'published_at': '', 'draft': False,
                'ended': False, 'url': 'https://example.com/project/7', 'event_label': 'publicado'}

    def test_sends_the_email_and_records_it(self):
        send_platform_notification('project-published', 'project-status-1', self._context())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Proyecto publicado: Proyecto', mail.outbox[0].subject)
        self.assertEqual(sorted(mail.outbox[0].to), ['dos@example.com', 'uno@example.com'])
        log = NotificationLog.objects.get(event='project-published', period_key='project-status-1')
        self.assertEqual(log.status, NotificationLog.STATUS_SENT)
        self.assertIsNotNone(log.sent_at)

    def test_a_repeated_job_does_not_send_twice(self):
        """Es el motivo de existir de NotificationLog: rq reintenta y el correo no puede duplicarse."""
        send_platform_notification('project-published', 'project-status-1', self._context())
        send_platform_notification('project-published', 'project-status-1', self._context())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_a_different_transition_does_send(self):
        send_platform_notification('project-published', 'project-status-1', self._context())
        send_platform_notification('project-republished', 'project-status-9', self._context())
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(PLATFORM_NOTIFICATION_EMAILS=[])
    def test_without_recipients_it_records_the_failure_instead_of_crashing(self):
        send_platform_notification('project-published', 'project-status-2', self._context())
        self.assertEqual(len(mail.outbox), 0)
        log = NotificationLog.objects.get(period_key='project-status-2')
        self.assertEqual(log.status, NotificationLog.STATUS_FAILED)
        self.assertIn('vacio', log.error)

    def test_organization_event(self):
        send_platform_notification('organization-created', 'organization-3', {
            'organization_id': 3, 'organization_name': 'Ibercivis', 'creator': 'fran',
            'event_label': 'creada', 'url': 'https://example.com/organization/3'})
        self.assertIn('Nueva organizacion: Ibercivis', mail.outbox[0].subject)

    def test_milestone_event(self):
        context = self._context()
        context.update(milestone=100, event_label='ha alcanzado 100 observaciones')
        send_platform_notification('project-milestone', 'project-7-milestone-100', context)
        self.assertIn('Proyecto: 100 observaciones', mail.outbox[0].subject)


class QueueIsolationTests(TestCase):
    """
    Guardarraíl: `manage.py test` no puede encolar en la cola de producción.

    Pasó el 2026-09-10 — la suite metió 8 jobs `project-milestone` en la cola real, de proyectos
    que solo existen en la base de test. Fallaron porque el worker aún no tenía el módulo, pero con
    el código ya desplegado habrían salido correos de verdad a los cuatro destinatarios.
    """

    def test_the_queue_points_to_a_scratch_redis_db_while_testing(self):
        from django.conf import settings
        self.assertEqual(settings.RQ_QUEUES['citisciapi']['DB'], 15)


@override_settings(
    CACHES=TEST_CACHES,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PLATFORM_NOTIFICATION_EMAILS=['uno@example.com'],
)
class DigestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(username='digestera', email='d@example.com')
        cls.project = _make_project(cls.creator, 'Con actividad')
        cls.now = timezone.now()
        _make_observation(cls.project, created_at=cls.now - timedelta(days=3))
        _make_observation(cls.project, created_at=cls.now - timedelta(days=100))

    def setUp(self):
        mail.outbox = []

    def test_window_falls_back_to_the_nominal_period_when_there_is_no_previous_digest(self):
        since, until = digest_window('fortnightly', now=self.now)
        self.assertEqual((until - since).days, 15)
        since, until = digest_window('month', now=self.now)
        self.assertEqual((until - since).days, 30)

    def test_window_starts_at_the_last_successful_digest(self):
        """
        Lo que evita los agujeros: si se perdió un envío, el siguiente cubre el hueco entero en vez
        de mirar solo los últimos 15 días.
        """
        NotificationLog.objects.create(
            event='digest', period_key='digest-viejo', status=NotificationLog.STATUS_SENT,
            sent_at=self.now - timedelta(days=40))
        since, until = digest_window('fortnightly', now=self.now)
        self.assertEqual((until - since).days, 40)

    def test_a_failed_digest_does_not_move_the_window(self):
        NotificationLog.objects.create(
            event='digest', period_key='digest-fallido', status=NotificationLog.STATUS_FAILED,
            sent_at=self.now - timedelta(days=3))
        since, until = digest_window('fortnightly', now=self.now)
        self.assertEqual((until - since).days, 15)

    def test_context_counts_only_the_window(self):
        context = build_digest_context('fortnightly', now=self.now)
        self.assertEqual(context['new_observations'], 1)   # la de hace 100 días queda fuera
        self.assertEqual(context['total_observations'], 2)
        self.assertEqual(context['top_projects'][0]['observations'], 1)

    def test_send_digest_sends_once_and_is_idempotent(self):
        send_digest('fortnightly')
        send_digest('fortnightly')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Resumen quincenal', mail.outbox[0].subject)
        log = NotificationLog.objects.get(event='digest')
        self.assertEqual(log.status, NotificationLog.STATUS_SENT)

    def test_the_subject_states_the_exact_range(self):
        send_digest('fortnightly')
        since, until = digest_window('fortnightly')
        self.assertIn(until.date().isoformat(), mail.outbox[0].subject)

    @override_settings(PLATFORM_NOTIFICATION_EMAILS=[])
    def test_without_recipients_it_records_the_failure(self):
        send_digest('fortnightly')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificationLog.objects.get(event='digest').status,
                         NotificationLog.STATUS_FAILED)

    def test_dry_run_neither_sends_nor_writes_a_log(self):
        out = StringIO()
        call_command('send_stats_digest', '--dry-run', stdout=out)
        self.assertIn('DRY RUN', out.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_the_command_sends(self):
        call_command('send_stats_digest', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)


class SchedulerRegistrationTests(TestCase):
    """
    El calendario vive en run_scheduler.py, en git, no solo en Redis. Estos tests van contra la
    DB 15 de Redis, la de pruebas, gracias al aislamiento de RQ_QUEUES.
    """

    def _scheduler(self):
        import django_rq
        return django_rq.get_scheduler('citisciapi')

    def tearDown(self):
        scheduler = self._scheduler()
        for job in scheduler.get_jobs():
            if job.id.startswith('geonity-'):
                scheduler.cancel(job)

    def test_register_only_registers_the_digest_with_a_fixed_id(self):
        call_command('run_scheduler', '--register-only', stdout=StringIO())
        ids = [job.id for job in self._scheduler().get_jobs()]
        self.assertIn('geonity-digest-monthly', ids)

    def test_registering_twice_does_not_duplicate(self):
        """Reiniciar el proceso no puede dejar dos veces el mismo trabajo periódico."""
        call_command('run_scheduler', '--register-only', stdout=StringIO())
        call_command('run_scheduler', '--register-only', stdout=StringIO())
        ids = [job.id for job in self._scheduler().get_jobs() if job.id.startswith('geonity-')]
        self.assertEqual(ids.count('geonity-digest-monthly'), 1)


class SchedulerTimezoneTests(TestCase):
    """
    La trampa de la zona horaria, fijada por escrito: Django sobrescribe TZ con su TIME_ZONE al
    cargar los settings, así que ponerlo solo en supervisord no sirve. Hay que re-fijarlo después.
    """

    def setUp(self):
        import os, time
        self._tz = os.environ.get('TZ')
        self.addCleanup(self._restore)

    def _restore(self):
        import os, time
        if self._tz is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self._tz
        time.tzset()

    def test_the_premise_of_the_problem(self):
        """
        Django fuerza el TZ del proceso a su TIME_ZONE, que aquí es UTC, mientras que los envíos se
        quieren en hora de Madrid. De esa diferencia nace todo lo demás. (No se comprueba
        `time.tzname` aquí: es estado global del proceso y cualquier otro test puede haberlo tocado.)
        """
        from django.conf import settings
        self.assertEqual(settings.TIME_ZONE, 'UTC')
        self.assertEqual(settings.PLATFORM_NOTIFICATION_TIMEZONE, 'Europe/Madrid')

    def test_apply_scheduler_timezone_switches_the_process_to_madrid(self):
        import time
        from stats.management.commands.run_scheduler import apply_scheduler_timezone
        self.assertEqual(apply_scheduler_timezone(), 'Europe/Madrid')
        self.assertIn(time.tzname[0], ('CET', 'CEST'))

    def test_the_cron_lands_at_08_00_local_in_both_halves_of_the_year(self):
        """08:00 locales todo el año: 06:00 UTC en verano, 07:00 UTC en invierno."""
        import datetime
        import crontab
        import dateutil.tz
        from zoneinfo import ZoneInfo
        from stats.management.commands.run_scheduler import apply_scheduler_timezone

        apply_scheduler_timezone()
        for ahora, utc_esperado in ((datetime.datetime(2026, 7, 10, 3, 0), 6),
                                    (datetime.datetime(2027, 1, 10, 3, 0), 7)):
            siguiente = crontab.CronTab('0 8 1 * *').next(
                now=ahora, return_datetime=True).astimezone(dateutil.tz.tzlocal())
            self.assertEqual(siguiente.hour, 8)
            self.assertEqual(siguiente.astimezone(ZoneInfo('UTC')).hour, utc_esperado)


@override_settings(CACHES=TEST_CACHES, PLATFORM_NOTIFICATION_EMAILS=['uno@example.com'])
class DigestInsightsTests(TestCase):
    """Comparación con el periodo anterior y datos de los gráficos."""

    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.creator = User.objects.create_user(username='insights', email='i@example.com')
        cls.project = _make_project(cls.creator, 'Evolución')
        # 2 en la quincena actual, 4 en la anterior -> caída del 50%
        for days in (1, 2):
            _make_observation(cls.project, created_at=cls.now - timedelta(days=days),
                              creator=cls.creator)
        for days in (17, 18, 19, 20):
            _make_observation(cls.project, created_at=cls.now - timedelta(days=days),
                              platform='web')

    def _context(self):
        return build_digest_context('fortnightly', now=self.now)

    def test_headline_compares_against_the_previous_window(self):
        observaciones = self._context()['headline'][0]
        self.assertEqual(observaciones['value'], 2)
        self.assertEqual(observaciones['previous'], 4)
        self.assertEqual(observaciones['delta_pct'], -50)
        self.assertEqual(observaciones['direction'], 'down')

    def test_no_percentage_is_invented_when_there_is_no_baseline(self):
        """Con 0 en el periodo anterior no hay porcentaje posible: se dice, no se inventa."""
        proyectos = self._context()['headline'][2]
        self.assertEqual(proyectos['previous'], 0)
        self.assertIsNone(proyectos['delta_pct'])

    def test_there_are_exactly_six_bars_per_chart(self):
        """
        Se arranca el día 1 del mes correspondiente. Con `until - 30*6 días` salían 7 barras y la
        primera era un mes a medias, o sea una caída falsa al principio de la serie.
        """
        for chart in self._context()['charts']:
            self.assertEqual(len(chart['bars']), 6, chart['title'])

    def test_bar_heights_are_scaled_to_the_maximum(self):
        bars = self._context()['charts'][0]['bars']
        alturas = [b['height'] for b in bars if b['count']]
        self.assertEqual(max(alturas), 80)
        self.assertTrue(all(b['height'] == 1 for b in bars if not b['count']))

    def test_the_platform_split_covers_the_period_not_all_of_history(self):
        context = self._context()
        self.assertEqual(sum(context['platform'].values()), context['new_observations'])
        self.assertEqual(context['platform']['web'], 0)          # las de web son del periodo anterior
        self.assertEqual(context['platform_all_time']['web'], 4)

    def test_contributors_are_counted_within_the_period(self):
        self.assertEqual(self._context()['contributors']['registered'], 1)


class AbandonedProjectsTests(TestCase):
    """
    Con el nombre delante el dato es accionable: "1 abandonado" no dice nada, "Flood2Now lleva 342
    días parado" sí.
    """

    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.creator = User.objects.create_user(username='dueña', email='d@example.com')
        cls.parado = _make_project(cls.creator, 'Parado hace mucho')
        cls.vivo = _make_project(cls.creator, 'Al día')
        cls.nunca = _make_project(cls.creator, 'Nunca recibió nada')
        cls.borrador = _make_project(cls.creator, 'Borrador viejo', draft=True)
        cls.terminado = _make_project(cls.creator, 'Terminado', ended=True)

        _make_observation(cls.parado, created_at=cls.now - timedelta(days=200))
        _make_observation(cls.vivo, created_at=cls.now - timedelta(days=2))
        _make_observation(cls.borrador, created_at=cls.now - timedelta(days=300))

    def _names(self):
        return [p['name'] for p in metrics.abandoned_projects(Project.objects.all(), now=self.now)]

    def test_lists_the_stale_published_project_with_its_days(self):
        rows = metrics.abandoned_projects(Project.objects.all(), now=self.now)
        parado = next(p for p in rows if p['name'] == 'Parado hace mucho')
        self.assertEqual(parado['days'], 200)

    def test_a_project_that_never_received_anything_appears_with_no_days(self):
        rows = metrics.abandoned_projects(Project.objects.all(), now=self.now)
        nunca = next(p for p in rows if p['name'] == 'Nunca recibió nada')
        self.assertIsNone(nunca['days'])

    def test_active_drafts_and_ended_projects_are_left_out(self):
        """Un borrador parado no es un problema, y uno terminado lo está a propósito."""
        names = self._names()
        self.assertNotIn('Al día', names)
        self.assertNotIn('Borrador viejo', names)
        self.assertNotIn('Terminado', names)

    def test_it_matches_the_abandoned_count(self):
        contados = metrics.project_metrics(Project.objects.all(), now=self.now)['abandoned']
        self.assertEqual(len(self._names()), contados)

    def test_the_digest_carries_the_names(self):
        context = build_digest_context('month', now=self.now)
        self.assertIn('Parado hace mucho', [p['name'] for p in context['abandoned_projects']])
