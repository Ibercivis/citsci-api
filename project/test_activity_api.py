"""Tests de GET /api/users/me/activity/ (project/api/activity.py)."""
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from markers.models import Observation, ObservationEmailLog, ObservationFieldValue, ProjectObservationField
from project.models import ProjectInvitation, ProjectStatusLog
from project.test_home_api import LOCMEM_CACHE, HomeApiTestCase


@override_settings(CACHES=LOCMEM_CACHE)
class ActivityTestCase(HomeApiTestCase):
    """`self.me` gestiona `self.mine`; `self.other` es otra persona; `self.foreign` es un proyecto ajeno."""

    def setUp(self):
        super().setUp()
        self.third = User.objects.create_user('third', 'third@example.com', 'pass1234')
        self.mine = self.make_project(creator=self.me, name='Mío')
        self.foreign = self.make_project(creator=self.other, name='Ajeno')
        self.client.force_authenticate(self.me)

    def feed(self, **params):
        response = self.client.get(reverse('my-activity'), params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def types(self, **params):
        return [item['type'] for item in self.feed(**params)['results']]

    def age(self, observation, days):
        """created_at es auto_now_add: para simular el pasado hay que usar update()."""
        Observation.objects.filter(pk=observation.pk).update(created_at=timezone.now() - timedelta(days=days))


class ParametersAndAccessTests(ActivityTestCase):
    def test_needs_a_session(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('my-activity')).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_parameters_are_a_400(self):
        for params in ({'scope': 'nope'}, {'page': 'x'}, {'project': 'x'}):
            with self.subTest(params=params):
                response = self.client.get(reverse('my-activity'), params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_when_the_user_manages_nothing(self):
        self.client.force_authenticate(self.third)
        data = self.feed()
        self.assertEqual((data['count'], data['results'], data['next']), (0, [], None))


class ScopeOfTheProjectsTests(ActivityTestCase):
    def test_only_events_in_projects_i_create_or_administer(self):
        self.observe(self.mine, self.other)
        self.observe(self.foreign, self.third)                      # proyecto ajeno: no sale
        self.observe(self.foreign, self.me)                         # mis observaciones en proyectos ajenos: no salen
        items = self.feed()['results']
        self.assertEqual([i['project']['id'] for i in items if i['type'] == 'observation_created'], [self.mine.id])

    def test_my_own_observations_in_my_projects_do_show(self):
        self.observe(self.mine, self.me)
        item = self.feed()['results'][0]
        self.assertEqual((item['type'], item['actor']['is_me']), ('observation_created', True))

    def test_administrators_see_the_projects_they_administer(self):
        self.foreign.administrators.add(self.me)
        self.observe(self.foreign, self.third)
        self.assertEqual(self.feed()['results'][0]['project']['id'], self.foreign.id)

    def test_a_project_i_both_create_and_administer_is_not_duplicated(self):
        self.mine.administrators.add(self.me)
        self.observe(self.mine, self.other)
        self.assertEqual(len(self.feed()['results']), 2)            # observación + participante, una sola vez cada una

    def test_drafts_and_ended_projects_count_too(self):
        draft = self.make_project(creator=self.me, name='Borrador', draft=True)
        ProjectStatusLog.objects.create(project=draft, event=ProjectStatusLog.EVENT_CREATED, by=self.me)
        self.assertEqual(self.types(), ['project_created'])

    def test_project_filter(self):
        second = self.make_project(creator=self.me, name='Segundo')
        self.observe(self.mine, self.other)
        self.observe(second, self.other)
        only_second = self.feed(project=second.id)['results']
        self.assertTrue(only_second)
        self.assertEqual({i['project']['id'] for i in only_second}, {second.id})

    def test_filtering_by_someone_elses_project_returns_nothing(self):
        self.observe(self.foreign, self.third)
        self.assertEqual(self.feed(project=self.foreign.id)['count'], 0)


class ScopeFilterTests(ActivityTestCase):
    def test_mine_and_others_split_by_actor(self):
        self.observe(self.mine, self.me)
        self.observe(self.mine, self.other)
        mine = self.feed(scope='mine')['results']
        others = self.feed(scope='others')['results']
        self.assertTrue(all(i['actor']['is_me'] for i in mine))
        self.assertTrue(all(not (i['actor'] or {}).get('is_me') for i in others))
        self.assertEqual(self.feed(scope='all')['count'], len(mine) + len(others))

    def test_anonymous_participants_belong_to_others(self):
        self.observe(self.mine, None, anonymous_id=uuid.uuid4())
        self.assertEqual(self.feed(scope='others')['count'], 1)
        self.assertEqual(self.feed(scope='mine')['count'], 0)


class ObservationEventsTests(ActivityTestCase):
    def test_observations_are_grouped_by_project_person_and_day(self):
        for _ in range(3):
            self.observe(self.mine, self.other)
        self.observe(self.mine, self.third)
        rows = [i for i in self.feed()['results'] if i['type'] == 'observation_created']
        self.assertEqual(sorted(r['meta']['count'] for r in rows), [1, 3])

    def test_a_single_observation_links_to_it(self):
        observation = self.observe(self.mine, self.other)
        row = next(i for i in self.feed()['results'] if i['type'] == 'observation_created')
        self.assertEqual(row['target'], {'observation_id': observation.id})
        self.assertEqual(row['meta']['count'], 1)

    def test_a_group_has_no_single_target(self):
        self.observe(self.mine, self.other)
        self.observe(self.mine, self.other)
        row = next(i for i in self.feed()['results'] if i['type'] == 'observation_created')
        self.assertIsNone(row['target'])

    def test_anonymous_observations_have_no_actor_and_are_grouped_together(self):
        self.observe(self.mine, None, anonymous_id=uuid.uuid4())
        self.observe(self.mine, None, anonymous_id=uuid.uuid4())
        rows = self.feed()['results']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['actor'])
        self.assertEqual((rows[0]['meta']['count'], rows[0]['meta']['anonymous']), (2, True))

    def test_observations_older_than_the_window_are_left_out(self):
        self.age(self.observe(self.mine, self.other), 120)
        self.assertEqual(self.feed()['count'], 0)

    def test_actor_exposes_the_username_and_never_the_email(self):
        self.observe(self.mine, self.other)
        actor = self.feed()['results'][0]['actor']
        self.assertEqual(actor, {'id': self.other.id, 'name': 'other', 'is_me': False})


class ParticipantJoinedTests(ActivityTestCase):
    def test_first_observation_of_a_person_is_a_new_participant(self):
        self.observe(self.mine, self.other)
        self.observe(self.mine, self.other)
        self.assertEqual(self.types().count('participant_joined'), 1)

    def test_a_person_whose_first_observation_is_old_is_not_new(self):
        old = self.observe(self.mine, self.other)
        self.age(old, 200)
        self.observe(self.mine, self.other)
        self.assertNotIn('participant_joined', self.types())

    def test_managers_do_not_count_as_new_participants(self):
        self.mine.administrators.add(self.third)
        self.observe(self.mine, self.me)
        self.observe(self.mine, self.third)
        self.assertNotIn('participant_joined', self.types())

    def test_anonymous_observations_do_not_create_participants(self):
        self.observe(self.mine, None, anonymous_id=uuid.uuid4())
        self.assertNotIn('participant_joined', self.types())


class OtherSourcesTests(ActivityTestCase):
    def test_project_status_changes_use_the_author(self):
        ProjectStatusLog.objects.create(project=self.mine, event=ProjectStatusLog.EVENT_PUBLISHED, by=self.other)
        ProjectStatusLog.objects.create(project=self.mine, event=ProjectStatusLog.EVENT_ENDED, by=self.me)
        by_type = {i['type']: i for i in self.feed()['results']}
        self.assertEqual(by_type['project_published']['actor']['name'], 'other')
        self.assertTrue(by_type['project_ended']['actor']['is_me'])

    def test_every_status_event_has_its_own_type(self):
        for event in (ProjectStatusLog.EVENT_CREATED, ProjectStatusLog.EVENT_PUBLISHED, ProjectStatusLog.EVENT_UNPUBLISHED,
                      ProjectStatusLog.EVENT_ENDED, ProjectStatusLog.EVENT_REOPENED):
            ProjectStatusLog.objects.create(project=self.mine, event=event, by=self.me)
        self.assertEqual(sorted(self.types()), sorted([
            'project_created', 'project_published', 'project_unpublished', 'project_ended', 'project_reopened']))

    def test_estimated_backfill_rows_are_ignored(self):
        ProjectStatusLog.objects.create(
            project=self.mine, event=ProjectStatusLog.EVENT_PUBLISHED, by=None, estimated=True)
        self.assertEqual(self.feed()['count'], 0)

    def test_admin_invitations_never_expose_the_invited_email(self):
        ProjectInvitation.objects.create(project=self.mine, email='guest@example.com', invited_by=self.me)
        row = self.feed()['results'][0]
        self.assertEqual((row['type'], row['actor']['is_me']), ('admin_invited', True))
        self.assertNotIn('guest@example.com', str(row))

    def test_management_edits_are_grouped_per_person_and_day(self):
        field = ProjectObservationField.objects.create(
            project=self.mine, key='validada', label='¿Validada?', field_type=ProjectObservationField.TYPE_BOOL)
        for _ in range(3):
            observation = self.observe(self.mine, self.other)
            ObservationFieldValue.objects.create(observation=observation, field=field, value=True, updated_by=self.me)
        row = next(i for i in self.feed(scope='mine')['results'] if i['type'] == 'observation_admin_fields_edited')
        self.assertEqual(row['meta']['count'], 3)

    def test_emails_are_grouped_and_only_sent_ones_count(self):
        sent_to = [self.observe(self.mine, self.other) for _ in range(2)]
        for observation in sent_to:
            ObservationEmailLog.objects.create(
                observation=observation, sent_by=self.me, subject='Hola', status=ObservationEmailLog.STATUS_SENT)
        failed = self.observe(self.mine, self.other)
        ObservationEmailLog.objects.create(
            observation=failed, sent_by=self.me, subject='Hola', status=ObservationEmailLog.STATUS_FAILED)
        row = next(i for i in self.feed(scope='mine')['results'] if i['type'] == 'observation_email_sent')
        self.assertEqual(row['meta']['count'], 2)


class OrderingAndPaginationTests(ActivityTestCase):
    def test_most_recent_first(self):
        old = self.observe(self.mine, self.other)
        self.age(old, 5)
        ProjectStatusLog.objects.create(project=self.mine, event=ProjectStatusLog.EVENT_ENDED, by=self.me)
        dates = [i['created_at'] for i in self.feed()['results']]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_pagination(self):
        for day in range(1, 6):
            self.age(self.observe(self.mine, self.other), day)    # 5 días distintos = 5 filas (+1 de participante)
        first = self.feed(page_size=2)
        self.assertEqual((len(first['results']), first['count']), (2, 6))
        self.assertIsNotNone(first['next'])
        self.assertIsNone(first['previous'])
        last = self.feed(page_size=2, page=3)
        self.assertIsNone(last['next'])
        self.assertIsNotNone(last['previous'])
        seen = [i['id'] for p in (1, 2, 3) for i in self.feed(page_size=2, page=p)['results']]
        self.assertEqual(len(seen), len(set(seen)))                # sin repetidos entre páginas

    def test_page_size_is_capped_at_fifty(self):
        for _ in range(55):
            ProjectStatusLog.objects.create(project=self.mine, event=ProjectStatusLog.EVENT_PUBLISHED, by=self.me)
        data = self.feed(page_size=999)
        self.assertEqual((data['count'], len(data['results'])), (55, 50))


class NoNPlusOneTests(ActivityTestCase):
    def queries(self, **params):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(reverse('my-activity'), params).status_code, status.HTTP_200_OK)
        return len(captured)

    def populate(self, how_many):
        for i in range(how_many):
            project = self.make_project(creator=self.me, name=f'P{i}')
            self.observe(project, self.other)
            ProjectStatusLog.objects.create(project=project, event=ProjectStatusLog.EVENT_PUBLISHED, by=self.me)

    def test_number_of_queries_does_not_grow_with_the_activity(self):
        self.populate(1)
        few = self.queries(page_size=50)
        self.populate(8)
        many = self.queries(page_size=50)
        self.assertEqual(few, many)
