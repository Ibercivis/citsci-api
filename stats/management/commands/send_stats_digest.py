"""
Resumen periodico, lanzable a mano.

El scheduler solo encola `stats.tasks.send_digest`; el trabajo de verdad esta aqui para poder
lanzarlo a mano, reenviar el de un periodo pasado y testearlo sin tocar Redis.
"""
from django.core.management.base import BaseCommand, CommandError

from stats.digest import PERIODS, build_digest_context, digest_period_key
from stats.tasks import send_digest


class Command(BaseCommand):
    help = 'Envia el resumen periodico de la plataforma a PLATFORM_NOTIFICATION_EMAILS.'

    def add_arguments(self, parser):
        parser.add_argument('--period', default='fortnightly', choices=sorted(PERIODS))
        parser.add_argument('--dry-run', action='store_true',
                            help='Calcula y muestra el resumen sin enviar nada ni registrar log.')

    def handle(self, *args, **options):
        period = options['period']
        context = build_digest_context(period)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN: no se envia nada'))
            self.stdout.write(f'  clave de idempotencia: {digest_period_key(context)}')
            for key, value in context.items():
                if key == 'top_projects':
                    for p in value:
                        self.stdout.write(f'    - {p["observations"]:>6}  {p["name"]}')
                else:
                    self.stdout.write(f'  {key}: {value}')
            return

        try:
            send_digest(period)
        except Exception as exc:
            raise CommandError(f'El resumen fallo: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Resumen {period} procesado'))
