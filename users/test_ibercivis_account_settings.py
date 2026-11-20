"""The Ibercivis account is declared by the environment, and only by it.

Each case reads the settings in a fresh interpreter, because they are read once,
at import: changing the environment of the process running the tests would
change nothing.
"""
import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

ISSUER = 'http://ibercivis.test/realms/citsci'

READ_THE_PROVIDERS = """
import json
import django
django.setup()
from django.conf import settings
print(json.dumps({
    'providers': settings.SOCIALACCOUNT_PROVIDERS,
    'redirect_uri': settings.IBERCIVIS_ACCOUNT_REDIRECT_URI,
}))
"""


def settings_read_with(**variables):
    environment = {
        name: value for name, value in os.environ.items()
        if not name.startswith('IBERCIVIS_ACCOUNT_')
    }
    environment.update(variables)
    environment['DJANGO_SETTINGS_MODULE'] = 'citsci-api.settings'
    output = subprocess.run(
        [sys.executable, '-c', READ_THE_PROVIDERS],
        cwd=settings.BASE_DIR, env=environment, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(output.strip().splitlines()[-1])


class IbercivisAccountSettingsTests(SimpleTestCase):
    def test_without_an_issuer_no_provider_is_declared(self):
        read = settings_read_with()

        self.assertNotIn('openid_connect', read['providers'])
        self.assertIn('google', read['providers'], 'Google sign-in must not depend on it')

    def test_with_an_issuer_the_provider_is_declared_from_the_environment(self):
        read = settings_read_with(
            IBERCIVIS_ACCOUNT_ISSUER=ISSUER,
            IBERCIVIS_ACCOUNT_CLIENT_ID='geonity',
            IBERCIVIS_ACCOUNT_CLIENT_SECRET='not-a-secret',
            IBERCIVIS_ACCOUNT_REDIRECT_URI='http://geonity.test/auth/ibercivis/callback',
        )

        provider = read['providers']['openid_connect']
        [app] = provider['APPS']
        self.assertEqual(provider['SCOPE'], ['openid', 'email'])
        self.assertEqual(app['provider_id'], 'ibercivis')
        self.assertEqual(app['client_id'], 'geonity')
        self.assertEqual(app['secret'], 'not-a-secret')
        self.assertEqual(app['settings']['server_url'], ISSUER)
        self.assertIs(app['settings']['fetch_userinfo'], False)
        self.assertEqual(read['redirect_uri'], 'http://geonity.test/auth/ibercivis/callback')
