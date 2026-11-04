"""An email address must not decide that two logins are the same person.

`pre_social_login` connected a brand-new social login to whatever local `User`
shared its email address, for every provider. Google is the only one configured
today, and these tests leave that case exactly as it was.

allauth offers the same behaviour as `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and
ships it off by default, documenting a condition on which providers it suits.
What these tests fix in place is that the behaviour is now a named set of
providers rather than the default for whatever is configured next.
"""
from allauth.account.models import EmailAddress
from allauth.socialaccount import app_settings as socialaccount_settings
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

# A provider that is not Google. Which id the Broker's own will carry is ticket
# 04's decision and nothing here depends on it: what these tests fix is that an
# email address connects nothing for any provider but the one the behaviour was
# written for.
A_PROVIDER_THAT_IS_NOT_GOOGLE = 'the-broker'


class SocialLoginEmailLinkingTests(TestCase):
    def setUp(self):
        self.veteran = User.objects.create_user('veteran', 'veteran@example.org', 'pass1234')
        self.request = RequestFactory().get('/')
        # The configured adapter, reached the way allauth reaches it in
        # allauth/socialaccount/internal/flows/login.py, so that pointing
        # SOCIALACCOUNT_ADAPTER elsewhere fails here too.
        self.adapter = get_adapter()

    def a_social_login(self, provider, email, verified=False):
        """A social login as allauth hands it to the adapter: nothing saved yet."""
        return SocialLogin(
            user=User(username='newcomer', email=email),
            account=SocialAccount(provider=provider, uid='248289761001'),
            email_addresses=[EmailAddress(email=email, verified=verified, primary=True)],
        )

    def test_a_federated_login_does_not_connect_to_the_local_user_with_the_same_email(self):
        # Verified or not. The verified case is the one that matters, because
        # connecting only when the provider says the address is verified is the
        # most tempting wrong fix: the provider's word about an address is not
        # a statement about who owns the local account.
        #
        # Measured, so that a red here is not mistaken for a broken test: put
        # the linking back and this case fails as an error, not as a failed
        # assertion, because connecting reaches for a provider that no
        # SocialApp registers. The rows are written by then all the same.
        for verified in (False, True):
            with self.subTest(verified=verified):
                sociallogin = self.a_social_login(
                    A_PROVIDER_THAT_IS_NOT_GOOGLE, self.veteran.email, verified=verified
                )

                self.adapter.pre_social_login(self.request, sociallogin)

                self.assertIsNone(sociallogin.user.pk, 'the login was connected to a stored user')
                self.assertFalse(sociallogin.is_existing, 'allauth would log in as the veteran')
                self.assertEqual(SocialAccount.objects.count(), 0)

    def test_google_keeps_connecting_to_the_local_user_with_the_same_email(self):
        # Production behaviour, untouched on purpose: Geonity's Google logins
        # have been landing on local accounts by email for years and changing
        # that is not this ticket's business. The guard is here so that a later
        # simplification of the adapter cannot change it in silence.
        sociallogin = self.a_social_login('google', self.veteran.email)

        self.adapter.pre_social_login(self.request, sociallogin)

        self.assertEqual(sociallogin.user.pk, self.veteran.pk)
        self.assertTrue(sociallogin.is_existing)
        self.assertEqual(SocialAccount.objects.filter(user=self.veteran).count(), 1)

    def test_allauth_is_not_allowed_to_connect_by_email_on_its_own(self):
        # The other half of the same door, and the half that cannot be seen by
        # reading the adapter: with SOCIALACCOUNT_EMAIL_AUTHENTICATION on,
        # allauth connects by email itself, for every provider at once and
        # before this adapter sees anything. It ships off and it stays off.
        self.assertFalse(socialaccount_settings.EMAIL_AUTHENTICATION)
        self.assertFalse(socialaccount_settings.EMAIL_AUTHENTICATION_AUTO_CONNECT)
