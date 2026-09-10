from django.db import IntegrityError, transaction
from django.test import TestCase

from stats.models import NotificationLog


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
