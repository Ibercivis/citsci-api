from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from organizations.models import Organization

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
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE)
    administrators = models.ManyToManyField(User, related_name='admin_projects')
    name = models.CharField(max_length=200, blank=False)
    description = models.CharField(max_length=200, blank=False)
    topic = models.ManyToManyField(Topic, blank=True)
    hasTag = models.ManyToManyField(HasTag, blank=True)
    organizations = models.ManyToManyField(Organization, related_name='projects')
