"""The API keeps creating accounts at `POST /api/users/registration/`; `users/api/urls.py`
says why. This case is here so that closing the web form is not mistaken for a reason to
tidy the endpoint away.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient


class RegistrationStaysOpen(TestCase):
    def test_the_endpoint_still_creates_an_account(self):
        response = APIClient().post('/api/users/registration/', {
            'email': 'newcomer@geonity.invalid',
            'password1': 'a-password-nobody-uses-1',
            'password2': 'a-password-nobody-uses-1',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(User.objects.filter(email='newcomer@geonity.invalid').exists())
