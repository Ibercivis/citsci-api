from django.db import models


class NotificationLog(models.Model):
    """
    Registro de los emails de plataforma (eventos y resumen periodico).

    `period_key` es la clave de idempotencia junto con `event`: para un evento de proyecto es el id
    de la fila de ProjectStatusLog que lo origina (`project-status-42`), y para el resumen periodico
    el periodo que cubre (`digest-2026-09`). El unique_together hace que un reintento de rq, o un
    disparo manual del comando, no envien el correo dos veces.

    Mismo planteamiento que markers.ObservationEmailLog, que ya guarda status/error por envio.
    """
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    event = models.CharField(max_length=64)
    period_key = models.CharField(max_length=128)
    subject = models.CharField(max_length=255, blank=True)
    recipients = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['event', 'period_key'], name='uniq_notification_event_period'),
        ]

    def __str__(self):
        return f"{self.event} {self.period_key} [{self.status}]"
