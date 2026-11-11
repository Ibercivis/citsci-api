"""Consentimiento de newsletter: alta opt-in, baja por enlace firmado y envío solo a suscritos."""
import os
import tempfile
from io import StringIO
from unittest import mock

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.api.serializers import CustomRegisterSerializer
from users.management.commands import send_email
from users.models import Profile
from users.newsletter import make_unsubscribe_token, unsubscribe_url


def make_user(name, subscribed=False, verified=True):
    user = User.objects.create_user(name, f'{name}@example.com', 'pass1234')
    EmailAddress.objects.create(user=user, email=user.email, verified=verified, primary=True)
    if subscribed:
        user.profile.set_newsletter(True)
    return user


class NewsletterStateTests(APITestCase):
    def setUp(self):
        self.user = make_user('ana')

    def test_nobody_is_subscribed_by_default(self):
        self.assertFalse(self.user.profile.newsletter_subscribed)

    def test_unsubscribing_keeps_the_acceptance_date_and_resubscribing_works(self):
        profile = self.user.profile
        profile.set_newsletter(True)
        accepted = profile.newsletter_accepted_at
        profile.set_newsletter(False)
        profile.refresh_from_db()
        self.assertFalse(profile.newsletter_subscribed)
        self.assertEqual(profile.newsletter_accepted_at, accepted)
        self.assertIsNotNone(profile.newsletter_revoked_at)
        profile.set_newsletter(True)
        profile.refresh_from_db()
        self.assertTrue(profile.newsletter_subscribed)

    def test_the_database_filter_agrees_with_the_property(self):
        on = make_user('on', subscribed=True)
        off = make_user('off', subscribed=True)
        off.profile.set_newsletter(False)
        back = make_user('back', subscribed=True)
        back.profile.set_newsletter(False)
        back.profile.set_newsletter(True)
        names = set(Profile.objects.filter(Profile.newsletter_subscribed_q())
                    .values_list('user__username', flat=True))
        self.assertEqual(names, {'on', 'back'})

    def test_signup_checkbox_is_opt_in(self):
        for sent, expected in (({}, False), ({'newsletter': False}, False), ({'newsletter': True}, True)):
            serializer = CustomRegisterSerializer(data={
                'email': 'x@example.com', 'password1': 'S3gura-clave!', 'password2': 'S3gura-clave!', **sent})
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.get_cleaned_data()['newsletter'], expected)


class NewsletterEndpointTests(APITestCase):
    def setUp(self):
        self.user = make_user('ana')
        self.url = reverse('user-newsletter')

    def test_requires_login(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.put(self.url, {'subscribed': True}).status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_subscribe_and_unsubscribe(self):
        self.client.force_authenticate(self.user)
        self.assertFalse(self.client.get(self.url).json()['subscribed'])
        response = self.client.put(self.url, {'subscribed': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['subscribed'])
        self.assertTrue(Profile.objects.get(user=self.user).newsletter_subscribed)
        response = self.client.put(self.url, {'subscribed': False}, format='json')
        self.assertFalse(response.json()['subscribed'])
        self.assertIsNotNone(response.json()['accepted_at'])

    def test_subscribed_is_required(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.put(self.url, {}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)


class UnsubscribeLinkTests(APITestCase):
    def setUp(self):
        self.user = make_user('ana', subscribed=True)
        self.url = reverse('newsletter-unsubscribe', args=[make_unsubscribe_token(self.user)])

    def test_get_does_not_unsubscribe(self):
        """Los antivirus y las previsualizaciones abren todos los enlaces de un correo."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Darme de baja')
        self.assertTrue(Profile.objects.get(user=self.user).newsletter_subscribed)

    def test_post_unsubscribes_without_login_or_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post(self.url, {'List-Unsubscribe': 'One-Click'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Profile.objects.get(user=self.user).newsletter_subscribed)
        # Repetirlo no falla ni cambia nada.
        self.assertEqual(client.post(self.url).status_code, 200)

    def test_a_tampered_token_is_rejected(self):
        other = make_user('otro', subscribed=True)
        bad = reverse('newsletter-unsubscribe', args=[make_unsubscribe_token(other)[:-2] + 'xx'])
        self.assertEqual(self.client.post(bad).status_code, 404)
        self.assertTrue(Profile.objects.get(user=other).newsletter_subscribed)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   BASE_URL='https://geonity.example')
class SendEmailCommandTests(APITestCase):
    def setUp(self):
        self.subscribed = make_user('sub', subscribed=True)
        self.plain = make_user('plain')
        self.unverified = make_user('unverified', subscribed=True, verified=False)
        self.gone = make_user('gone', subscribed=True)
        self.gone.profile.set_newsletter(False)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        with open(os.path.join(self.dir.name, 'news.html'), 'w', encoding='utf-8') as f:
            f.write('<h1>Hola</h1><p>Mira <a href="https://geonity.example/x">esto</a> &amp; más.</p>')
        patcher = mock.patch.object(send_email, 'EMAILS_DIR', self.dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, *args):
        call_command('send_email', 'news', '--subject', 'Novedades', *args, stdout=StringIO())
        return mail.outbox

    def test_subscribed_only_reaches_verified_subscribers(self):
        outbox = self.send('--subscribed')
        self.assertEqual([m.to for m in outbox], [['sub@example.com']])

    def test_newsletter_carries_the_unsubscribe_link_and_headers(self):
        message = self.send('--subscribed')[0]
        url = unsubscribe_url(self.subscribed)
        self.assertEqual(message.extra_headers['List-Unsubscribe'], f'<{url}>')
        self.assertEqual(message.extra_headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
        self.assertIn(url, message.body)
        self.assertIn(url, message.alternatives[0][0])

    def test_plain_text_comes_from_the_html(self):
        body = self.send('--subscribed')[0].body
        self.assertIn('Hola', body)
        self.assertIn('esto (https://geonity.example/x) & más.', body)
        self.assertNotIn('<', body.split('--')[0])

    def test_a_txt_file_next_to_the_html_wins(self):
        with open(os.path.join(self.dir.name, 'news.txt'), 'w', encoding='utf-8') as f:
            f.write('Texto escrito a mano')
        self.assertTrue(self.send('--subscribed')[0].body.startswith('Texto escrito a mano'))

    def test_all_verified_is_a_service_notice_without_unsubscribe(self):
        outbox = self.send('--all-verified')
        self.assertEqual({m.to[0] for m in outbox},
                         {'sub@example.com', 'plain@example.com', 'gone@example.com'})
        for message in outbox:
            self.assertNotIn('List-Unsubscribe', message.extra_headers)
            self.assertNotIn('Darme de baja', message.alternatives[0][0])
