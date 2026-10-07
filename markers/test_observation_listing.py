"""GET /api/observations/ devuelve las observaciones de todos los proyectos: solo staff."""
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from field_forms.models import FieldForm
from markers.api.permissions import PLATFORM_KEYS
from markers.models import Observation
from project.models import Project

LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCMEM_CACHE)
class ObservationListingTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'pass1234')
        self.visitor = User.objects.create_user('visitor', 'visitor@example.com', 'pass1234')
        self.staff = User.objects.create_user('staff', 'staff@example.com', 'pass1234', is_staff=True)
        self.project = Project.objects.create(
            creator=self.owner, name='Proyecto', description={'default': 'desc'}, draft=False)
        self.field_form = FieldForm.objects.create(project=self.project)
        self.observation = Observation.objects.create(
            creator=self.owner, field_form=self.field_form, timestamp=timezone.now(),
            geoposition=Point(-0.88, 41.65), data={})
        self.url = reverse('observation_list_create')

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_a_regular_user_cannot_list_every_observation(self):
        self.client.force_authenticate(self.visitor)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_not_even_the_owner_of_a_project_can(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([o['id'] for o in response.json()], [self.observation.id])

    def test_creating_an_observation_is_unchanged(self):
        """Sigue pidiendo sesión y clave de cliente; con ambas llega a la validación (400), no a un 403."""
        self.client.force_authenticate(self.visitor)
        self.assertEqual(self.client.post(self.url, {}).status_code, status.HTTP_403_FORBIDDEN)   # sin clave de cliente
        with_key = self.client.post(self.url, {}, HTTP_X_API_KEY=PLATFORM_KEYS['web'])
        self.assertEqual(with_key.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_per_project_listing_still_works_for_regular_users(self):
        self.client.force_authenticate(self.visitor)
        response = self.client.get(reverse('observation_by_field_form_list', args=[self.field_form.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([o['id'] for o in response.json()], [self.observation.id])

    def test_the_per_project_listing_still_protects_private_projects(self):
        self.project.is_private = True
        self.project.save()
        self.client.force_authenticate(self.visitor)
        response = self.client.get(reverse('observation_by_field_form_list', args=[self.field_form.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_my_observations_still_works(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse('my_observations'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([o['id'] for o in response.json()], [self.observation.id])
