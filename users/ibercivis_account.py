"""Signing in with an Ibercivis account: redeeming the code the web app brings back.

allauth ships the OpenID Connect provider and dj-rest-auth ships the view that
redeems an authorization code, as it does for Google. What is here is the part
neither does on its own, and nothing more:

* dj-rest-auth builds the adapter as `adapter_class(request)`, while allauth's
  OpenID Connect adapter also needs the provider's id.
* dj-rest-auth redeems the code without a PKCE verifier. The Ibercivis service
  requires one, because the code was obtained in a browser: allauth's client
  accepts it, and `VerifierForwardingClient` passes it on.
* dj-rest-auth also accepts a bare `access_token` instead of a code. Here only a
  code is accepted, so every sign-in goes through the token request this API
  makes itself, with its own secret, and the ID token it gets back has its
  signature checked against the service's published keys.
"""
import functools

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from dj_rest_auth.registration.serializers import SocialLoginSerializer
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import NotFound


class IbercivisAccountAdapter(OpenIDConnectOAuth2Adapter):
    def __init__(self, request):
        super().__init__(request, settings.IBERCIVIS_ACCOUNT_PROVIDER)


class VerifierForwardingClient(OAuth2Client):
    def __init__(self, *args, code_verifier, **kwargs):
        super().__init__(*args, **kwargs)
        self.code_verifier = code_verifier

    def get_access_token(self, code, pkce_code_verifier=None, extra_data=None):
        return super().get_access_token(
            code, pkce_code_verifier=self.code_verifier, extra_data=extra_data,
        )


class IbercivisAccountLoginSerializer(SocialLoginSerializer):
    # Removed, so a token obtained anywhere else cannot be handed in instead of a code.
    access_token = None
    id_token = None
    code = serializers.CharField()
    code_verifier = serializers.CharField()

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except OAuth2Error as refused:
            # An ID token that fails its checks: signature, issuer, audience, expiry.
            # dj-rest-auth lets this one through as a server error.
            raise serializers.ValidationError(_('Incorrect value')) from refused


class IbercivisAccountLoginView(SocialLoginView):
    adapter_class = IbercivisAccountAdapter
    serializer_class = IbercivisAccountLoginSerializer

    @property
    def callback_url(self):
        return settings.IBERCIVIS_ACCOUNT_REDIRECT_URI

    @property
    def client_class(self):
        # Read when the serializer redeems the code, after its fields have been validated.
        return functools.partial(
            VerifierForwardingClient, code_verifier=self.request.data['code_verifier'],
        )

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except SocialApp.DoesNotExist as unconfigured:
            # No IBERCIVIS_ACCOUNT_ISSUER: the way in does not exist on this deployment.
            raise NotFound() from unconfigured
