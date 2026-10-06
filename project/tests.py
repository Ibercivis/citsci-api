from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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

