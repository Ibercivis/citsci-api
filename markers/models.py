from django.db import models
from django.contrib.auth.models import User
from field_forms.models import FieldForm, Question

# Create your models here.

# Define el modelo Marker, que está asociado a un FieldForm y a un usuario, y tiene coordenadas geográficas
class Marker(models.Model):
    field_form = models.ForeignKey(FieldForm, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    latitude = models.FloatField()
    longitude = models.FloatField()
    # ...

# Define el modelo Answer, que está asociado a un Marker y a una Question, y contiene un valor "value" de respuesta
class Answer(models.Model):
    marker = models.ForeignKey(Marker, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    value = models.TextField()