"""users/ y users/<pk>/ listan cualquier usuario ignorando su preferencia de visibilidad: solo staff."""
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class UserListingTests(APITestCase):
    def setUp(self):
        self.regular = User.objects.create_user('regular', 'regular@example.com', 'pass1234')
        self.hidden = User.objects.create_user('hidden', 'hidden@example.com', 'pass1234')
        self.public = User.objects.create_user('public', 'public@example.com', 'pass1234')
        self.staff = User.objects.create_user('staff', 'staff@example.com', 'pass1234', is_staff=True)
        for user, visible in ((self.hidden, False), (self.public, True)):
            user.profile.visibility = visible
            user.profile.save()

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get(reverse('users')).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.get(reverse('users-detail', args=[self.hidden.pk])).status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_a_regular_user_cannot_list_users_or_open_someone_elses_profile(self):
        self.client.force_authenticate(self.regular)
        self.assertEqual(self.client.get(reverse('users')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('users-detail', args=[self.hidden.pk])).status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_staff_can(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(reverse('users')).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(reverse('users-detail', args=[self.hidden.pk])).status_code,
                         status.HTTP_200_OK)

    def test_the_visible_users_list_keeps_respecting_the_profile_preference(self):
        self.client.force_authenticate(self.regular)
        response = self.client.get(reverse('user-list-visible'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [u['username'] for u in response.json()]
        self.assertIn('public', names)
        self.assertNotIn('hidden', names)

    def test_own_profile_is_unaffected(self):
        self.client.force_authenticate(self.regular)
        self.assertEqual(self.client.get(reverse('user-profile')).status_code, status.HTTP_200_OK)
