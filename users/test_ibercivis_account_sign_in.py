"""Signing in with an Ibercivis account, through `POST /api/users/auth/ibercivis/`.

The web app sends the person to the Ibercivis sign-in service, comes back with an
authorization code, and posts it here with the PKCE verifier it kept. The API
redeems the code with its own secret and answers with the token a password
sign-in answers with.

No case talks to the network. The service's three answers this needs -- its
discovery document, its token endpoint and its signing keys -- are played by
`TheService` below, which signs ID tokens with a key made for the test run.
"""
import json
import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

ISSUER = 'http://ibercivis.test/realms/citsci'
CLIENT_ID = 'geonity'
REDIRECT_URI = 'http://geonity.test/auth/ibercivis/callback'
TOKEN_ENDPOINT = f'{ISSUER}/protocol/openid-connect/token'
JWKS_URI = f'{ISSUER}/protocol/openid-connect/certs'

SIGN_IN = '/api/users/auth/ibercivis/'

IBERCIVIS_ACCOUNT = {
    'openid_connect': {
        'SCOPE': ['openid', 'email'],
        'APPS': [{
            'provider_id': 'ibercivis',
            'name': 'Ibercivis',
            'client_id': CLIENT_ID,
            'secret': 'not-a-secret',
            'settings': {'server_url': ISSUER, 'fetch_userinfo': False},
        }],
    },
}

# What the service says in an ID token about somebody who has just signed in. The
# identifier is the only thing it promises never changes, and nothing in it says
# how the person proved who they are: a Google account, an ORCID, a password.
IBERCIVIS_ACCOUNT_ID = '3d7ba8aa-1f1e-4b0e-9a3f-1d2c3b4a5e6f@ibercivis.es'
SAYS = {
    'sub': IBERCIVIS_ACCOUNT_ID,
    'voperson_id': IBERCIVIS_ACCOUNT_ID,
    'email': 'arrival@geonity.invalid',
    'email_verified': True,
    'acr': '1',
}

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
A_KEY_THE_SERVICE_NEVER_HAD = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def an_id_token(key=SIGNING_KEY, **claims):
    now = int(time.time())
    body = {'iss': ISSUER, 'aud': CLIENT_ID, 'iat': now, 'exp': now + 300, **SAYS, **claims}
    return jwt.encode(body, key, algorithm='RS256', headers={'kid': 'the-key'})


class Answer:
    def __init__(self, body, status_code=200):
        self.status_code = status_code
        self.text = json.dumps(body)
        self.content = self.text.encode()
        self.headers = {'content-type': 'application/json'}
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f'{self.status_code} was not expected here')


class TheService:
    """The sign-in service, as far as allauth's requests session can tell."""

    def __init__(self, id_token):
        self.id_token = id_token
        self.token_requests = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **_):
        if url == f'{ISSUER}/.well-known/openid-configuration':
            return Answer({
                'issuer': ISSUER,
                'authorization_endpoint': f'{ISSUER}/protocol/openid-connect/auth',
                'token_endpoint': TOKEN_ENDPOINT,
                'userinfo_endpoint': f'{ISSUER}/protocol/openid-connect/userinfo',
                'jwks_uri': JWKS_URI,
                'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post'],
            })
        if url == JWKS_URI:
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key()))
            return Answer({'keys': [{**jwk, 'kid': 'the-key', 'use': 'sig', 'alg': 'RS256'}]})
        raise AssertionError(f'nothing here should ask for {url}')

    def request(self, method, url, data=None, **_):
        if (method, url) != ('POST', TOKEN_ENDPOINT):
            raise AssertionError(f'nothing here should ask for {method} {url}')
        self.token_requests.append(data)
        return Answer({
            'access_token': 'an-access-token',
            'token_type': 'Bearer',
            'expires_in': 300,
            'id_token': self.id_token,
        })


@override_settings(
    SOCIALACCOUNT_PROVIDERS=IBERCIVIS_ACCOUNT,
    IBERCIVIS_ACCOUNT_REDIRECT_URI=REDIRECT_URI,
)
class SignInCase(TestCase):
    def sign_in(self, id_token=None, **posted):
        self.service = TheService(id_token or an_id_token())
        body = {'code': 'an-authorization-code', 'code_verifier': 'the-verifier', **posted}
        body = {name: value for name, value in body.items() if value is not None}
        with mock.patch(
            'allauth.socialaccount.adapter.DefaultSocialAccountAdapter.get_requests_session',
            return_value=self.service,
        ):
            return APIClient().post(SIGN_IN, body, format='json')

    def me(self, key):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {key}')
        return client.get('/api/users/authentication/user/').json()


class RedeemingTheCode(SignInCase):
    def test_a_valid_code_answers_with_the_token_a_password_sign_in_answers_with(self):
        response = self.sign_in()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(response.json()), ['key'])

        self.assertEqual(self.me(response.json()['key'])['email'], SAYS['email'])

    def test_the_token_request_carries_the_verifier_and_the_pinned_callback(self):
        self.sign_in(code_verifier='what-the-browser-kept')

        [sent] = self.service.token_requests
        self.assertEqual(sent['code'], 'an-authorization-code')
        self.assertEqual(sent['code_verifier'], 'what-the-browser-kept')
        self.assertEqual(sent['redirect_uri'], REDIRECT_URI)
        self.assertEqual(sent['client_id'], CLIENT_ID)
        self.assertEqual(sent['client_secret'], 'not-a-secret')

    def test_the_callback_cannot_be_chosen_by_whoever_posts(self):
        self.sign_in(redirect_uri='http://elsewhere.test/callback', callback_url='http://elsewhere.test/')

        [sent] = self.service.token_requests
        self.assertEqual(sent['redirect_uri'], REDIRECT_URI)


class RefusingTheIdToken(SignInCase):
    """Every refusal leaves no account behind, and no token."""

    def assert_refused(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertNotIn('key', response.json())
        self.assertFalse(User.objects.filter(email=SAYS['email']).exists())

    def test_a_token_signed_by_another_key_is_refused(self):
        self.assert_refused(self.sign_in(an_id_token(key=A_KEY_THE_SERVICE_NEVER_HAD)))

    def test_a_token_issued_to_another_application_is_refused(self):
        self.assert_refused(self.sign_in(an_id_token(aud='lostatnight')))

    def test_a_token_from_another_issuer_is_refused(self):
        self.assert_refused(self.sign_in(an_id_token(iss='http://impostor.test/realms/citsci')))

    def test_an_expired_token_is_refused(self):
        an_hour_ago = int(time.time()) - 3600
        self.assert_refused(self.sign_in(an_id_token(iat=an_hour_ago - 300, exp=an_hour_ago)))


class RefusingTheRequest(SignInCase):
    def test_an_access_token_instead_of_a_code_is_refused(self):
        response = self.sign_in(code=None, access_token='a-token-from-somewhere-else')

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('code', response.json())
        self.assertEqual(self.service.token_requests, [])

    def test_a_code_without_its_verifier_is_refused(self):
        response = self.sign_in(code_verifier=None)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('code_verifier', response.json())
        self.assertEqual(self.service.token_requests, [])

    @override_settings(SOCIALACCOUNT_PROVIDERS={})
    def test_without_an_ibercivis_account_configured_the_address_does_not_exist(self):
        self.assertEqual(self.sign_in().status_code, 404)
