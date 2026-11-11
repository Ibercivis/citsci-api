import html
import os
import re
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from users.models import Profile
from users.newsletter import unsubscribe_headers, unsubscribe_url

EMAILS_DIR = os.path.join(settings.BASE_DIR, 'emails')


class Command(BaseCommand):
    help = (
        'Send an HTML email using a template from the emails/ folder via Amazon SES.\n\n'
        'Examples:\n'
        '  python manage.py send_email welcome --subject "Bienvenido" --to user@example.com\n'
        '  python manage.py send_email newsletter --subject "Novedades" --subscribed --dry-run\n'
        '  python manage.py send_email newsletter --subject "Novedades" --subscribed\n'
        '  python manage.py send_email welcome --subject "Test" --test me@example.com\n'
        '  python manage.py send_email --list'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'email_file',
            nargs='?',
            help='Name of the HTML file in emails/ folder (without .html extension)',
        )
        parser.add_argument(
            '--subject', '-s',
            help='Email subject line',
        )
        parser.add_argument(
            '--to', '-t',
            nargs='+',
            metavar='EMAIL',
            help='Recipient email address(es)',
        )
        parser.add_argument(
            '--test',
            metavar='EMAIL',
            help='Send only to this address (ignores --to), useful for previewing',
        )
        parser.add_argument(
            '--subscribed',
            action='store_true',
            help='Send to every user who opted in to the newsletter and has a verified email address',
        )
        parser.add_argument(
            '--all-verified',
            action='store_true',
            help='Send to ALL users with a verified email address, subscribed or not. Only for '
                 'service notices every user must get (e.g. a change in the terms); never for news.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show recipients without actually sending',
        )
        parser.add_argument(
            '--list', '-l',
            action='store_true',
            help='List available email templates in emails/ folder',
        )

    def handle(self, *args, **options):
        if options['list']:
            self._list_emails()
            return

        email_file = options.get('email_file')
        if not email_file:
            raise CommandError('Provide an email file name or use --list to see available templates.')

        subject = options.get('subject')
        if not subject:
            raise CommandError('--subject is required.')

        if options.get('test'):
            recipients = [options['test']]
        elif options.get('subscribed'):
            from allauth.account.models import EmailAddress
            recipients = list(
                EmailAddress.objects
                .filter(Profile.newsletter_subscribed_q('user__profile__'), verified=True, primary=True)
                .values_list('email', flat=True)
            )
        elif options.get('all_verified'):
            from allauth.account.models import EmailAddress
            recipients = list(
                EmailAddress.objects.filter(verified=True).values_list('email', flat=True)
            )
        else:
            recipients = options.get('to') or []

        if not recipients:
            raise CommandError('Provide recipients with --to, --subscribed, --all-verified, or use --test <email>.')

        html_path = os.path.join(EMAILS_DIR, f'{email_file}.html')
        if not os.path.isfile(html_path):
            available = self._available_files()
            raise CommandError(
                f'File not found: emails/{email_file}.html\n'
                f'Available: {", ".join(available) if available else "(none)"}'
            )

        with open(html_path, 'r', encoding='utf-8') as f:
            raw_html = f.read()

        # Version en texto plano: emails/<nombre>.txt si existe; si no, se saca del HTML. Un texto
        # plano de relleno ("Ver version HTML") es una de las cosas que miran los filtros de spam.
        txt_path = os.path.join(EMAILS_DIR, f'{email_file}.txt')
        if os.path.isfile(txt_path):
            with open(txt_path, 'r', encoding='utf-8') as f:
                raw_text = f.read().strip()
        else:
            raw_text = self._html_to_text(raw_html)

        # El enlace de baja solo va en los envios a suscritos. Un aviso de servicio (--all-verified)
        # no es newsletter: ofrecer ahi la baja haria creer que uno puede dejar de recibirlos.
        # Tampoco con --to: esos destinatarios no tienen por que haber aceptado la newsletter y el pie
        # dice lo contrario. --test si lo lleva (si la direccion es de un usuario), para previsualizar.
        with_unsubscribe = bool(options.get('subscribed') or options.get('test'))
        users_by_email = {}
        if with_unsubscribe:
            users_by_email = {
                u.email.lower(): u for u in User.objects.filter(email__in=recipients)
            }

        from_email = settings.DEFAULT_FROM_EMAIL
        dry_run = options.get('dry_run')
        mode = 'DRY-RUN' if dry_run else ('TEST' if options.get('test') else 'SEND')

        self.stdout.write(f'[{mode}] Subject:    {subject}')
        self.stdout.write(f'[{mode}] From:       {from_email}')
        self.stdout.write(f'[{mode}] Recipients: {len(recipients)}')

        if dry_run:
            for email in recipients:
                self.stdout.write(f'  - {email}')
            self.stdout.write(self.style.WARNING('Dry run — no emails sent.'))
            return

        sent = 0
        failed = 0
        for email in recipients:
            try:
                user = users_by_email.get(email.lower())
                context = {'custom_content': raw_html}
                text_body = raw_text
                headers = {}
                if user is not None:
                    context['unsubscribe_url'] = unsubscribe_url(user)
                    text_body += f'\n\n--\nDarme de baja: {context["unsubscribe_url"]}'
                    headers = unsubscribe_headers(user)
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=from_email,
                    to=[email],
                    headers=headers,
                )
                msg.attach_alternative(render_to_string('email/base_custom.html', context), 'text/html')
                msg.send(fail_silently=False)
                sent += 1
                self.stdout.write(f'  OK  {email}')
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f'  FAIL {email}: {e}'))

        self.stdout.write(self.style.SUCCESS(f'Done — sent: {sent}, failed: {failed}.'))

    @staticmethod
    def _html_to_text(raw_html):
        text = re.sub(r'(?is)<(style|script)\b.*?</\1>', '', raw_html)
        # Los enlaces conservan su URL, que en texto plano es lo unico que importa de ellos.
        text = re.sub(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'\2 (\1)', text)
        text = re.sub(r'(?i)<br\s*/?>|</(p|h[1-6]|tr|li|div|table)>', '\n', text)
        text = html.unescape(strip_tags(text))
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()

    def _available_files(self):
        if not os.path.isdir(EMAILS_DIR):
            return []
        return [f[:-5] for f in os.listdir(EMAILS_DIR) if f.endswith('.html')]

    def _list_emails(self):
        files = self._available_files()
        if not files:
            self.stdout.write('No email templates found in emails/ folder.')
            return
        self.stdout.write(self.style.SUCCESS(f'{len(files)} template(s) in emails/:'))
        for name in sorted(files):
            self.stdout.write(f'  - {name}')
