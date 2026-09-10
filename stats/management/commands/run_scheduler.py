"""
Scheduler de rq. Lo mantiene vivo supervisord (program citsci-scheduler).

Registra los trabajos periodicos con id fijo ANTES de arrancar el bucle. Eso hace dos cosas:
el registro es idempotente (reiniciar no duplica trabajos) y, sobre todo, **el calendario efectivo
vive en este fichero, en git**, no solo en Redis. Si alguien vacia Redis o se migra de maquina, un
`supervisorctl restart citsci-scheduler` lo reconstruye.

La hora de los cron la interpreta rq-scheduler en la zona horaria del PROCESO, y ahi hay una
trampa: **Django sobrescribe TZ con su TIME_ZONE** (aqui "UTC") al cargar los settings, llamando a
time.tzset(). Poner TZ=Europe/Madrid solo en el program de supervisord NO sirve: Django lo pisa
antes de que rq-scheduler mire la hora. Por eso se re-fija aqui, en handle(), cuando Django ya ha
terminado de cargar. Comprobado: sin esto el cron sale a las 08:00 UTC (10:00 en Madrid); con esto,
a las 08:00 locales tanto en verano (06:00 UTC) como en invierno (07:00 UTC).

Cambiar TZ solo afecta a este proceso, que no hace mas que calcular horas y encolar. Quien ejecuta
es el worker, con su propio entorno, y todas las fechas de la base son aware en UTC (USE_TZ=True).
"""
import os
import time

import django_rq
from django.conf import settings
from django.core.management.base import BaseCommand


def apply_scheduler_timezone():
    """Re-fija TZ despues de Django. Ver la explicacion de arriba: sin esto el cron se va a UTC."""
    tz = settings.PLATFORM_NOTIFICATION_TIMEZONE
    os.environ['TZ'] = tz
    time.tzset()
    return tz

SCHEDULED_JOBS = [
    {
        'id': 'geonity-digest-monthly',
        'cron': '0 8 1 * *',
        'func': 'stats.tasks.send_digest',
        'args': ['month'],
        'description': 'Resumen mensual de plataforma (dia 1 a las 08:00 hora local)',
    },
    {
        'id': 'geonity-project-digests-monthly',
        'cron': '0 9 1 * *',
        'func': 'stats.tasks.send_project_digests',
        'args': ['month'],
        # Una hora despues del de plataforma, para no soltar todos los correos a la vez.
        'description': 'Informe mensual a cada proyecto (dia 1 a las 09:00 hora local)',
    },
]


class Command(BaseCommand):
    help = 'Registra los trabajos periodicos y arranca el scheduler de rq.'

    def add_arguments(self, parser):
        parser.add_argument('--register-only', action='store_true',
                            help='Registra los trabajos y sale, sin arrancar el bucle.')

    def handle(self, *args, **options):
        tz = apply_scheduler_timezone()
        self.stdout.write(f'  zona horaria del proceso: {tz} ({time.tzname})')
        scheduler = django_rq.get_scheduler('citisciapi')

        # Se cancela lo nuestro antes de registrar: asi cambiar un cron en este fichero se aplica
        # al reiniciar, en vez de dejar el viejo vivo en Redis para siempre.
        known = {job['id'] for job in SCHEDULED_JOBS}
        for job in scheduler.get_jobs():
            if job.id in known or job.id.startswith('geonity-'):
                scheduler.cancel(job)
                self.stdout.write(f'  cancelado el registro anterior de {job.id}')

        for spec in SCHEDULED_JOBS:
            scheduler.cron(
                spec['cron'],
                func=spec['func'],
                args=spec['args'],
                id=spec['id'],
                queue_name='citisciapi',
                use_local_timezone=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f'  registrado {spec["id"]}: {spec["cron"]} -> {spec["func"]}{spec["args"]}'))

        for job, when in scheduler.get_jobs(with_times=True):
            if job.id.startswith('geonity-'):
                self.stdout.write(f'  proxima ejecucion de {job.id}: {when:%Y-%m-%d %H:%M} UTC')

        if options['register_only']:
            return

        self.stdout.write('Scheduler arrancado, esperando.')
        scheduler.run()
