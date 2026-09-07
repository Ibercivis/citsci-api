import json
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from field_forms.models import FieldForm, Question
from markers.models import Observation
from project.models import Project

LOCMEM_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


def throttle_rates(**rates):
    """
    Sustituye los ratios de throttle durante un test.

    override_settings no sirve: DRF copia DEFAULT_THROTTLE_RATES en
    SimpleRateThrottle.THROTTLE_RATES al importar el módulo, y ahí se queda.
    """
    merged = {**settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'], **rates}
    return patch.object(SimpleRateThrottle, 'THROTTLE_RATES', merged)


@override_settings(CACHES=LOCMEM_CACHE)
class AnonymousContributionTests(APITestCase):
    """Contribución anónima por QR: /api/anonymous/<token>/"""

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'pass1234')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass1234')
        self.project = Project.objects.create(
            creator=self.owner,
            name='Proyecto QR',
            description={'default': 'Un proyecto con QR'},
            draft=False,
            anonymous_contribution=True,
        )
        self.field_form = FieldForm.objects.create(project=self.project)
        self.q_text = Question.objects.create(
            field_form=self.field_form,
            question_text={'default': '¿Qué has visto?'},
            answer_type=Question.STRING,
            mandatory=True,
            order=1,
        )
        self.q_choice = Question.objects.create(
            field_form=self.field_form,
            question_text={'default': 'Estado'},
            answer_type=Question.CHOICE,
            choices=[{'value': 'bueno', 'label': {'default': 'Bueno'}}],
            order=2,
        )
        self.q_mchoice = Question.objects.create(
            field_form=self.field_form,
            question_text={'default': 'Colores'},
            answer_type=Question.MULTICHOICE,
            choices=[{'value': 'rojo', 'label': {'default': 'Rojo'}}],
            order=3,
        )
        self.anonymous_id = str(uuid.uuid4())

    # -- helpers ---------------------------------------------------------

    def info_url(self, token=None):
        return reverse('anonymous_project_info', args=[token or self.project.anonymous_token])

    def create_url(self, token=None):
        return reverse('anonymous_observation_create', args=[token or self.project.anonymous_token])

    def mine_url(self, token=None):
        return reverse('anonymous_observations_mine', args=[token or self.project.anonymous_token])

    def payload(self, data=None):
        if data is None:
            data = [{'key': str(self.q_text.id), 'value': 'Un mirlo'}]
        return {
            'data': json.dumps(data),
            'timestamp': '2026-09-07T10:00:00Z',
            'geoposition': 'POINT (-0.88 41.65)',
        }

    def post_observation(self, data=None, anonymous_id='', url=None):
        headers = {}
        if anonymous_id != '':
            headers['HTTP_X_ANONYMOUS_ID'] = anonymous_id
        else:
            headers['HTTP_X_ANONYMOUS_ID'] = self.anonymous_id
        return self.client.post(url or self.create_url(), self.payload(data), format='multipart', **headers)

    # -- GET landing -----------------------------------------------------

    def test_info_returns_project_and_form(self):
        response = self.client.get(self.info_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['project']['name'], 'Proyecto QR')
        question_ids = [q['id'] for q in response.data['field_form']['questions']]
        self.assertEqual(question_ids, [self.q_text.id, self.q_choice.id, self.q_mchoice.id])

    def test_info_404_when_flag_off(self):
        self.project.anonymous_contribution = False
        self.project.save(update_fields=['anonymous_contribution'])
        self.assertEqual(self.client.get(self.info_url()).status_code, status.HTTP_404_NOT_FOUND)

    def test_info_404_when_project_ended(self):
        self.project.ended = True
        self.project.save(update_fields=['ended'])
        self.assertEqual(self.client.get(self.info_url()).status_code, status.HTTP_404_NOT_FOUND)

    def test_info_works_for_draft_projects(self):
        # El QR tiene que funcionar en borrador: publicar exige >10 observaciones
        self.project.draft = True
        self.project.save(update_fields=['draft'])
        self.assertEqual(self.client.get(self.info_url()).status_code, status.HTTP_200_OK)
        self.assertEqual(self.post_observation().status_code, status.HTTP_201_CREATED)

    def test_info_404_for_unknown_token(self):
        self.assertEqual(self.client.get(self.info_url(uuid.uuid4())).status_code, status.HTTP_404_NOT_FOUND)

    def test_post_404_when_flag_off(self):
        self.project.anonymous_contribution = False
        self.project.save(update_fields=['anonymous_contribution'])
        self.assertEqual(self.post_observation().status_code, status.HTTP_404_NOT_FOUND)

    # -- POST observación ------------------------------------------------

    def test_post_creates_anonymous_observation(self):
        response = self.post_observation()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        observation = Observation.objects.get(pk=response.data['id'])
        self.assertIsNone(observation.creator)
        self.assertEqual(str(observation.anonymous_id), self.anonymous_id)
        self.assertEqual(observation.platform, Observation.PLATFORM_WEB)
        self.assertTrue(response.data['is_anonymous'])
        # El pseudónimo no puede salir en la respuesta: con él se reclaman las observaciones
        self.assertNotIn('anonymous_id', response.data)

    def test_post_stores_sanitized_source(self):
        response = self.post_observation(url=self.create_url() + '?src=cartel<>-plaza')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        observation = Observation.objects.get(pk=response.data['id'])
        self.assertEqual(observation.anonymous_source, 'cartel-plaza')

    def test_post_without_anonymous_id_header(self):
        response = self.client.post(self.create_url(), self.payload(), format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Observation.objects.count(), 0)

    def test_post_with_invalid_anonymous_id(self):
        response = self.post_observation(anonymous_id='no-soy-un-uuid')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Observation.objects.count(), 0)

    def test_post_rejected_when_project_is_mobile_only(self):
        self.project.allowed_platforms = Project.PLATFORM_MOBILE
        self.project.save(update_fields=['allowed_platforms'])
        response = self.post_observation()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Observation.objects.count(), 0)

    def test_post_requires_mandatory_questions(self):
        response = self.post_observation(data=[{'key': str(self.q_choice.id), 'value': 'bueno'}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Observation.objects.count(), 0)

    def test_post_validates_choice_values(self):
        response = self.post_observation(data=[
            {'key': str(self.q_text.id), 'value': 'Un mirlo'},
            {'key': str(self.q_choice.id), 'value': 'inventado'},
        ])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_validates_multichoice_values(self):
        response = self.post_observation(data=[
            {'key': str(self.q_text.id), 'value': 'Un mirlo'},
            {'key': str(self.q_mchoice.id), 'value': ['rojo', 'violeta']},
        ])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_rejects_unknown_question(self):
        response = self.post_observation(data=[
            {'key': str(self.q_text.id), 'value': 'Un mirlo'},
            {'key': '999999', 'value': 'x'},
        ])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- GET mine --------------------------------------------------------

    def test_mine_only_returns_own_observations(self):
        self.post_observation()
        other_browser = str(uuid.uuid4())
        self.post_observation(anonymous_id=other_browser)
        self.assertEqual(Observation.objects.count(), 2)

        response = self.client.get(self.mine_url(), HTTP_X_ANONYMOUS_ID=self.anonymous_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_mine_requires_anonymous_id_header(self):
        response = self.client.get(self.mine_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- Throttling ------------------------------------------------------

    @throttle_rates(anon_submit='2/hour', anon_submit_id='100/hour')
    def test_submit_throttled_by_ip(self):
        self.assertEqual(self.post_observation().status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.post_observation(anonymous_id=str(uuid.uuid4())).status_code, status.HTTP_201_CREATED)
        response = self.post_observation(anonymous_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @throttle_rates(anon_submit='100/hour', anon_submit_id='1/hour')
    def test_submit_throttled_by_anonymous_id(self):
        self.assertEqual(self.post_observation().status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.post_observation().status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        # Otro navegador desde la misma IP sigue pudiendo enviar
        self.assertEqual(self.post_observation(anonymous_id=str(uuid.uuid4())).status_code, status.HTTP_201_CREATED)

    # -- Token -----------------------------------------------------------

    def test_regenerate_token_invalidates_old_qr(self):
        old_token = self.project.anonymous_token
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse('project-regenerate-anonymous-token', args=[self.project.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        new_token = response.data['anonymous_token']
        self.assertNotEqual(str(old_token), new_token)

        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.info_url(old_token)).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(self.info_url(new_token)).status_code, status.HTTP_200_OK)

    def test_regenerate_token_denied_to_strangers(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(reverse('project-regenerate-anonymous-token', args=[self.project.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Anónimo + privado ------------------------------------------------

    def test_project_cannot_be_private_and_anonymous(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            reverse('project_retrieve_update_destroy', args=[self.project.id]),
            {'is_private': True, 'raw_password': 'secreta123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('anonymous_contribution', response.data)

    def test_private_project_cannot_enable_anonymous(self):
        self.project.anonymous_contribution = False
        self.project.is_private = True
        self.project.save(update_fields=['anonymous_contribution', 'is_private'])

        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            reverse('project_retrieve_update_destroy', args=[self.project.id]),
            {'anonymous_contribution': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('anonymous_contribution', response.data)

    # -- La vista autenticada no se relaja ---------------------------------

    def test_authenticated_post_still_requires_api_key(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(
            reverse('observation_list_create'),
            {**self.payload(), 'field_form': self.field_form.id},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Observation.objects.count(), 0)

    def test_authenticated_post_still_works(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(
            reverse('observation_list_create'),
            {**self.payload(), 'field_form': self.field_form.id},
            format='multipart',
            HTTP_X_API_KEY=settings.CLIENT_API_KEY_WEB,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        observation = Observation.objects.get(pk=response.data['id'])
        self.assertEqual(observation.creator, self.other)
        self.assertIsNone(observation.anonymous_id)
        self.assertFalse(response.data['is_anonymous'])

    # -- Borrado -----------------------------------------------------------

    def test_project_admin_can_delete_anonymous_observation(self):
        response = self.post_observation()
        observation_id = response.data['id']

        self.client.force_authenticate(user=self.other)
        url = reverse('observation_retrieve', args=[observation_id])
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Observation.objects.count(), 0)
