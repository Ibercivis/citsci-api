"""Tests de las rutas de solo lectura de Inicio y Gestionar (project/api/home.py)."""
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from field_forms.models import FieldForm
from markers.models import Observation
from organizations.models import Invitation as OrganizationInvitation
from organizations.models import Organization
from project.models import Project, ProjectInvitation, ProjectMembership, ProjectStatusLog

# Guardar una Observation invalida cachés (señal): en los tests, caché en memoria.
LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


class HomeApiTestCase(APITestCase):
    def setUp(self):
        self.me = User.objects.create_user('me', 'Me@Example.com', 'pass1234')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass1234')

    def make_project(self, creator=None, name='Proyecto', **kwargs):
        kwargs.setdefault('draft', False)
        project = Project.objects.create(
            creator=creator or self.other, name=name, description={'default': 'desc'}, **kwargs)
        FieldForm.objects.create(project=project)
        return project

    def observe(self, project, user=None, when=None, anonymous_id=None):
        return Observation.objects.create(
            creator=user, anonymous_id=anonymous_id, field_form=project.fieldform,
            timestamp=when or timezone.now(), geoposition=Point(-0.88, 41.65), data={},
        )


@override_settings(CACHES=LOCMEM_CACHE)
class AuthRequiredTests(HomeApiTestCase):
    def test_all_routes_need_a_session(self):
        for name in ('my-impact', 'my-pending-count', 'home-continue', 'manage-projects'):
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CACHES=LOCMEM_CACHE)
class MyImpactTests(HomeApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.me)
        self.project = self.make_project()

    def get(self):
        response = self.client.get(reverse('my-impact'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_user_without_activity(self):
        data = self.get()
        self.assertEqual(data['observations'], 0)
        self.assertEqual(data['projects_participating'], 0)
        self.assertEqual(data['this_month'], {'value': 0, 'previous': 0, 'delta_pct': None, 'direction': 'flat'})
        self.assertIsNone(data['last_observation'])
        self.assertEqual(data['streak_weeks'], 0)

    def test_counts_only_my_observations(self):
        self.observe(self.project, self.me)
        self.observe(self.project, self.me)
        self.observe(self.project, self.other)
        self.assertEqual(self.get()['observations'], 2)

    def test_projects_participating_counts_observations_and_memberships_once(self):
        other_project = self.make_project(name='Otro')
        self.make_project(name='Tercero')              # sin observaciones ni membresía: no participa
        self.observe(self.project, self.me)
        self.observe(self.project, self.me)           # el mismo proyecto no cuenta dos veces
        ProjectMembership.objects.create(project=other_project, user=self.me)
        self.assertEqual(self.get()['projects_participating'], 2)

    def test_this_month_compares_with_the_previous_month(self):
        now = timezone.now()
        this_month = now.replace(day=1, hour=12)
        previous = (this_month - timedelta(days=5)).replace(hour=12)
        for _ in range(3):
            self.observe(self.project, self.me, when=this_month)
        for _ in range(2):
            self.observe(self.project, self.me, when=previous)
        month = self.get()['this_month']
        self.assertEqual(month['value'], 3)
        self.assertEqual(month['previous'], 2)
        self.assertEqual(month['delta_pct'], 50)
        self.assertEqual(month['direction'], 'up')

    def test_streak_counts_consecutive_weeks_and_tolerates_an_empty_current_week(self):
        now = timezone.now()
        for weeks_ago in (1, 2, 3):                   # la semana en curso aún vacía no rompe la racha
            self.observe(self.project, self.me, when=now - timedelta(weeks=weeks_ago))
        self.assertEqual(self.get()['streak_weeks'], 3)

    def test_streak_breaks_after_a_week_without_contributions(self):
        now = timezone.now()
        self.observe(self.project, self.me, when=now - timedelta(weeks=1))
        self.observe(self.project, self.me, when=now - timedelta(weeks=3))   # hueco en la semana -2
        self.assertEqual(self.get()['streak_weeks'], 1)


@override_settings(CACHES=LOCMEM_CACHE)
class MyPendingCountTests(HomeApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.me)

    def test_counts_project_and_organization_invitations_for_my_email(self):
        project = self.make_project()
        org = Organization.objects.create(principalName='Org', creator=self.other)
        ProjectInvitation.objects.create(project=project, email='me@example.com', invited_by=self.other)
        ProjectInvitation.objects.create(project=project, email='me@example.com', invited_by=self.other, status='accepted')
        ProjectInvitation.objects.create(project=project, email='other@example.com', invited_by=self.other)
        # Las invitaciones de organización se buscan con el e-mail tal cual lo guarda el usuario (igual que
        # `organization/invitations/pending/`), así que el contador coincide con esa lista.
        OrganizationInvitation.objects.create(
            organization=org, email=self.me.email, role='member', invited_by=self.other)
        data = self.client.get(reverse('my-pending-count')).json()
        self.assertEqual(data, {'invitations': 2, 'projects': 1, 'organizations': 1})

    def test_matches_the_existing_pending_lists(self):
        project = self.make_project()
        ProjectInvitation.objects.create(project=project, email='me@example.com', invited_by=self.other)
        listed = self.client.get(reverse('project-invitations-pending')).json()
        counted = self.client.get(reverse('my-pending-count')).json()
        self.assertEqual(counted['projects'], len(listed))

    def test_zero_when_nothing_is_pending(self):
        self.assertEqual(self.client.get(reverse('my-pending-count')).json(),
                         {'invitations': 0, 'projects': 0, 'organizations': 0})


@override_settings(CACHES=LOCMEM_CACHE)
class HomeContinueTests(HomeApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.me)

    def get(self):
        response = self.client.get(reverse('home-continue'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_lists_only_projects_where_i_participate_most_recent_first(self):
        old, recent = self.make_project(name='Antiguo'), self.make_project(name='Reciente')
        self.make_project(name='Ajeno')
        now = timezone.now()
        self.observe(old, self.me, when=now - timedelta(days=10))
        self.observe(recent, self.me, when=now - timedelta(days=1))
        self.assertEqual([p['name'] for p in self.get()], ['Reciente', 'Antiguo'])

    def test_includes_my_own_projects_but_not_drafts(self):
        own = self.make_project(creator=self.me, name='Mío')
        draft = self.make_project(creator=self.me, name='Borrador', draft=True)
        self.observe(own, self.me)
        self.observe(draft, self.me)
        self.assertEqual([p['name'] for p in self.get()], ['Mío'])

    def test_counts_are_the_project_total_and_mine(self):
        project = self.make_project()
        self.observe(project, self.me)
        self.observe(project, self.me)
        self.observe(project, self.other)
        item = self.get()[0]
        self.assertEqual(item['observations_count'], 3)
        self.assertEqual(item['my_observations_count'], 2)
        self.assertIsNotNone(item['my_last_observation'])

    def test_membership_without_observations_still_counts(self):
        project = self.make_project(name='Con contraseña')
        ProjectMembership.objects.create(project=project, user=self.me)
        item = self.get()[0]
        self.assertEqual(item['name'], 'Con contraseña')
        self.assertEqual(item['my_observations_count'], 0)
        self.assertIsNone(item['my_last_observation'])

    def test_ended_projects_are_flagged(self):
        project = self.make_project(ended=True)
        self.observe(project, self.me)
        self.assertTrue(self.get()[0]['ended'])

    def test_limited_to_twenty(self):
        for i in range(22):
            self.observe(self.make_project(name=f'P{i}'), self.me)
        self.assertEqual(len(self.get()), 20)


@override_settings(CACHES=LOCMEM_CACHE)
class ManageProjectsTests(HomeApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.me)
        self.active = self.make_project(creator=self.me, name='Activo')
        self.draft = self.make_project(creator=self.me, name='Borrador', draft=True)
        self.ended = self.make_project(creator=self.me, name='Finalizado', ended=True)
        self.administered = self.make_project(creator=self.other, name='Administrado')
        self.administered.administrators.add(self.me)
        self.make_project(creator=self.other, name='Ajeno')

    def get(self, **params):
        return self.client.get(reverse('manage-projects'), params)

    def test_counts_cover_the_three_tabs_whatever_status_is_asked(self):
        for wanted in ('active', 'draft', 'ended'):
            with self.subTest(status=wanted):
                self.assertEqual(self.get(status=wanted).json()['counts'],
                                 {'active': 2, 'draft': 1, 'ended': 1})

    def test_status_filters_the_results(self):
        names = lambda wanted: sorted(p['name'] for p in self.get(status=wanted).json()['results'])  # noqa: E731
        self.assertEqual(names('active'), ['Activo', 'Administrado'])
        self.assertEqual(names('draft'), ['Borrador'])
        self.assertEqual(names('ended'), ['Finalizado'])

    def test_active_is_the_default(self):
        self.assertEqual(sorted(p['name'] for p in self.get().json()['results']), ['Activo', 'Administrado'])

    def test_role_is_owner_or_admin(self):
        roles = {p['name']: p['role'] for p in self.get(status='active').json()['results']}
        self.assertEqual(roles, {'Activo': 'owner', 'Administrado': 'admin'})

    def test_other_users_projects_never_appear(self):
        everything = [p['name'] for s in ('active', 'draft', 'ended') for p in self.get(status=s).json()['results']]
        self.assertNotIn('Ajeno', everything)

    def test_participants_count_adds_registered_users_and_anonymous_browsers(self):
        self.observe(self.active, self.me)
        self.observe(self.active, self.other)
        self.observe(self.active, self.other)                      # misma persona: cuenta una vez
        self.observe(self.active, None, anonymous_id=uuid.uuid4())
        self.observe(self.active, None, anonymous_id=uuid.uuid4())
        item = next(p for p in self.get().json()['results'] if p['name'] == 'Activo')
        self.assertEqual(item['participants_count'], 4)
        self.assertEqual(item['observations_count'], 5)
        self.assertTrue(item['has_observations'])

    def test_project_without_observations(self):
        item = next(p for p in self.get().json()['results'] if p['name'] == 'Activo')
        self.assertEqual((item['participants_count'], item['observations_count'], item['has_observations']),
                         (0, 0, False))

    def test_last_activity_is_the_latest_of_observation_and_status_change(self):
        past = timezone.now() - timedelta(days=30)
        self.observe(self.active, self.me, when=past)
        ProjectStatusLog.objects.create(project=self.active, event=ProjectStatusLog.EVENT_PUBLISHED, by=self.me)
        item = next(p for p in self.get().json()['results'] if p['name'] == 'Activo')
        self.assertGreater(item['last_activity_at'], past.isoformat().replace('+00:00', 'Z'))

    def test_pagination(self):
        first = self.get(status='active', page_size=1).json()
        self.assertEqual((first['count'], len(first['results'])), (2, 1))
        self.assertIsNotNone(first['next'])
        self.assertIsNone(first['previous'])
        second = self.get(status='active', page_size=1, page=2).json()
        self.assertIsNone(second['next'])
        self.assertIsNotNone(second['previous'])
        self.assertNotEqual(first['results'][0]['id'], second['results'][0]['id'])

    def test_invalid_parameters_are_a_400(self):
        self.assertEqual(self.get(status='nope').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.get(page='x').status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_without_projects(self):
        self.client.force_authenticate(User.objects.create_user('empty', 'empty@example.com', 'pass1234'))
        data = self.get().json()
        self.assertEqual(data['counts'], {'active': 0, 'draft': 0, 'ended': 0})
        self.assertEqual((data['count'], data['results'], data['next']), (0, [], None))


@override_settings(CACHES=LOCMEM_CACHE)
class NoNPlusOneTests(HomeApiTestCase):
    """El número de consultas no debe crecer con el número de proyectos (los contadores van anotados)."""

    def queries(self, route):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(reverse(route)).status_code, status.HTTP_200_OK)
        return len(captured)

    def populate(self, how_many):
        for i in range(how_many):
            project = self.make_project(creator=self.me, name=f'P{i}')
            self.observe(project, self.me)
            self.observe(project, self.other)

    def test_continue_and_manage_use_a_constant_number_of_queries(self):
        self.client.force_authenticate(self.me)
        self.populate(1)
        few = {r: self.queries(r) for r in ('home-continue', 'manage-projects')}
        self.populate(6)
        many = {r: self.queries(r) for r in ('home-continue', 'manage-projects')}
        # Las organizaciones de cada proyecto se cargan con prefetch: el número de consultas sigue siendo el mismo.
        self.assertEqual(few, many)

