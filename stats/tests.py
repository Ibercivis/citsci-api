from datetime import timedelta

from django.contrib.auth.models import User
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
