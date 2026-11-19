from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from django.contrib.auth.models import User
import requests


class CustomGoogleOAuth2Adapter(GoogleOAuth2Adapter):
    def complete_login(self, request, app, token, **kwargs):
        response = kwargs.get("response", {})
        if not isinstance(response, dict) or "id_token" not in response:
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token.token}"}
            )
            resp.raise_for_status()
            extra_data = resp.json()
            login = self.get_provider().sociallogin_from_response(request, extra_data)
            return login
        return super().complete_login(request, app, token, **kwargs)


# Providers whose email address may connect a social login to an existing local
# account. An address says where to reach somebody, not who they are, so this
# stays an exception for the provider it was written for: allauth offers the
# same behaviour as SOCIALACCOUNT_EMAIL_AUTHENTICATION, ships it off by default,
# and documents a condition on which providers it suits. Any provider added
# later has to be put here deliberately.
#
# Behind the Broker, what says two logins are the same person is the Identity's
# own persistent identifier, never the address.
AUTO_CONNECT_BY_EMAIL_PROVIDERS = {"google"}


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return
        if sociallogin.account.provider not in AUTO_CONNECT_BY_EMAIL_PROVIDERS:
            return
        if not sociallogin.email_addresses:
            return
        email = sociallogin.email_addresses[0].email
        try:
            user = User.objects.get(email=email)
            sociallogin.connect(request, user)
        except User.DoesNotExist:
            pass
