from django.contrib.gis.db import models as gis_models
from django.db import models
from django.db.models import JSONField
from django.contrib.auth.models import User
from field_forms.models import FieldForm, Question

class Observation(models.Model):
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='observations')
    field_form = models.ForeignKey(FieldForm, on_delete=models.CASCADE, related_name='observations')
    timestamp = models.DateTimeField()
    geoposition = gis_models.PointField()
    data = JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ObservationImage(models.Model):
    observation = models.ForeignKey(Observation, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='images/')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
