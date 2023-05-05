from django.contrib.gis.db import models as gis_models
from django.db import models
from django.contrib.postgres.fields import JSONField
from field_forms.models import FieldForm

class Observation(models.Model):
    field_form = models.ForeignKey(FieldForm, on_delete=models.CASCADE, related_name='observations')
    timestamp = models.DateTimeField()
    geoposition = gis_models.PointField()
    data = JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)