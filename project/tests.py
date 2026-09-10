from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from project.models import Project, ProjectStatusLog


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
