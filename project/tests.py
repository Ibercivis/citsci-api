from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from project.models import Project, ProjectInvitation, ProjectStatusLog


class ProjectStatusLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='creator', email='creator@example.com')
        cls.project = Project.objects.create(
            creator=cls.user,
            name='Proyecto de prueba',
            description={'default': 'desc'},
        )

    def test_new_project_has_no_published_at(self):
        self.assertIsNone(self.project.published_at)

    def test_at_can_be_written_with_a_historical_date(self):
        """
        `at` usa default=timezone.now y no auto_now_add precisamente para esto: el backfill de la
        migracion necesita escribir fechas del pasado, y auto_now_add las pisaria.
        """
        past = timezone.now() - timezone.timedelta(days=365)
        log = ProjectStatusLog.objects.create(
            project=self.project, event=ProjectStatusLog.EVENT_CREATED, at=past, by=self.user,
        )
        log.refresh_from_db()
        self.assertEqual(log.at, past)

    def test_ordering_is_most_recent_first(self):
        now = timezone.now()
        old = ProjectStatusLog.objects.create(
            project=self.project, event=ProjectStatusLog.EVENT_CREATED,
            at=now - timezone.timedelta(days=2),
        )
        new = ProjectStatusLog.objects.create(
            project=self.project, event=ProjectStatusLog.EVENT_PUBLISHED, at=now,
        )
        self.assertEqual(list(self.project.status_log.all()), [new, old])

    def test_deleting_the_project_deletes_its_log(self):
        ProjectStatusLog.objects.create(project=self.project, event=ProjectStatusLog.EVENT_CREATED)
        self.project.delete()
        self.assertEqual(ProjectStatusLog.objects.count(), 0)

    def test_deleting_the_user_keeps_the_log_row(self):
        """`by` es SET_NULL: borrar la cuenta no debe borrar el historico del proyecto."""
        other = User.objects.create_user(username='admin2', email='a2@example.com')
        log = ProjectStatusLog.objects.create(
            project=self.project, event=ProjectStatusLog.EVENT_PUBLISHED, by=other,
        )
        other.delete()
        log.refresh_from_db()
        self.assertIsNone(log.by)


class ProjectAcceptInvitationTests(APITestCase):
    """
    POST /api/project/invitations/<id>/accept/

    Regresión: la respuesta se serializaba con una clase (`ProjectSerializer`) mal declarada que lanzaba
    AssertionError, así que la invitación se aceptaba en base de datos pero el cliente recibía un 500
    (y al reintentar, un 400 «ya fue accepted»).
    """

    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'pass1234')
        self.invited = User.objects.create_user('invited', 'Invited@Example.com', 'pass1234')
        self.stranger = User.objects.create_user('stranger', 'stranger@example.com', 'pass1234')
        self.project = Project.objects.create(
            creator=self.owner, name='Proyecto', description={'default': 'desc'}, draft=False,
        )
        self.invitation = ProjectInvitation.objects.create(
            project=self.project, email='invited@example.com', invited_by=self.owner,
        )

    def url(self):
        return reverse('project-invitation-accept', args=[self.invitation.id])

    def test_accept_returns_200_with_the_project(self):
        self.client.force_authenticate(self.invited)
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data['project']['id'], self.project.id)
        self.assertIn('message', response.data)

    def test_accept_makes_the_user_administrator_and_closes_the_invitation(self):
        self.client.force_authenticate(self.invited)
        self.client.post(self.url())
        self.assertTrue(self.project.administrators.filter(id=self.invited.id).exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'accepted')

    def test_accepting_twice_is_a_400_not_a_500(self):
        self.client.force_authenticate(self.invited)
        self.client.post(self.url())
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_someone_else_cannot_accept(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'pending')


class ExploreDraftsTests(TestCase):
    url = '/api/explore/drafts/'

    def setUp(self):
        self.client = APIClient()

    @classmethod
    def setUpTestData(cls):
        cls.me = User.objects.create_user(username='me', email='me@example.com')
        cls.other = User.objects.create_user(username='other', email='other@example.com')
        cls.my_draft = Project.objects.create(
            creator=cls.me, name='Mi borrador', description={'default': 'd'}, draft=True)
        cls.other_draft = Project.objects.create(
            creator=cls.other, name='Borrador ajeno', description={'default': 'd'}, draft=True,
            anonymous_contribution=True)
        cls.published = Project.objects.create(
            creator=cls.other, name='Publicado', description={'default': 'd'}, draft=False)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_returns_other_users_drafts_and_never_published(self):
        self.client.force_authenticate(user=self.me)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        ids = {p['id'] for p in response.json()}
        self.assertEqual(ids, {self.my_draft.id, self.other_draft.id})
        self.assertNotIn(self.published.id, ids)
        self.assertTrue(all(p['draft'] for p in response.json()))

    def test_is_a_plain_array_sorted_by_updated_at_desc(self):
        self.client.force_authenticate(user=self.me)
        data = self.client.get(self.url).json()
        self.assertIsInstance(data, list)
        updated = [p['updated_at'] for p in data]
        self.assertEqual(updated, sorted(updated, reverse=True))

    def test_keys_match_project_list(self):
        self.client.force_authenticate(user=self.me)
        draft_keys = set(self.client.get(self.url).json()[0].keys())
        list_keys = set(self.client.get('/api/project/').json()[0].keys())
        self.assertEqual(draft_keys, list_keys)

    def test_anonymous_token_only_for_creator_or_admin(self):
        self.client.force_authenticate(user=self.me)
        by_id = {p['id']: p for p in self.client.get(self.url).json()}
        self.assertIsNone(by_id[self.other_draft.id]['anonymous_token'])
        self.client.force_authenticate(user=self.other)
        by_id = {p['id']: p for p in self.client.get(self.url).json()}
        self.assertEqual(by_id[self.other_draft.id]['anonymous_token'],
                         str(self.other_draft.anonymous_token))
