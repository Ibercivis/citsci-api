from django.db import models
from projects.models import Project

# Create your models here.

# Define el modelo FieldForm, que está asociado a un proyecto
class FieldForm(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE)

# Define el modelo Question, que está asociado a un FieldForm y tiene un tipo de respuesta
class Question(models.Model):
    STRING = 'STR'
    NUMBER = 'NUM'
    DATE = 'DATE'
    IMAGE = 'IMG'
    QUESTION_TYPES = [
        (STRING, 'String'),
        (NUMBER, 'Number'),
        (DATE, 'Date'),
        (IMAGE, 'Image'),
    ]
    
    field_form = models.ForeignKey(FieldForm, on_delete=models.CASCADE)
    question_text = models.CharField(max_length=200)
    answer_type = models.CharField(max_length=4, choices=QUESTION_TYPES)