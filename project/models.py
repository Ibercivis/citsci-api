from django.db import models
from django.conf import settings
from django.contrib.auth.models import User

# Create your models here.

class Topic(models.Model):
    topic = models.TextField()

    def __str__(self):
        return f'{self.topic}'

class HasTag(models.Model):
    hasTag = models.TextField()

    def __str__(self):
        return f'{self.hasTag}'

# Define el modelo Project que tiene un propietario, un nombre, una descripción y un topic (el hasTag creo que no tiene sentido)
class Project(models.Model):
    creator = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200, blank=False)
    description = models.CharField(max_length=200, blank=False)
    topic = models.ManyToManyField(Topic, blank=True)
    hasTag = models.ManyToManyField(HasTag, blank=True)
