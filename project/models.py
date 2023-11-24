from django.db import models
from django.db.models import ImageField
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
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
    description = models.CharField(max_length=1000, blank=False)
    topic = models.ManyToManyField(Topic, blank=True)
    hasTag = models.ManyToManyField(HasTag, blank=True)
    is_private = models.BooleanField(default=False)
    _password = models.CharField(max_length=128, blank=True, null=True)
    organizations = models.ManyToManyField(Organization, related_name='projects')
    likes = models.ManyToManyField(User, related_name='liked_projects', blank=True)

    @property
    def total_likes(self):
        return self.likes.count()
    
    @property
    def password(self):
        raise AttributeError("No se puede leer el atributo password directamente")

    @password.setter
    def password(self, raw_password):
        self._password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self._password)


    def toggle_like(self, user):
        if self.likes.filter(id=user.id).exists():
            self.likes.remove(user)
            return False  # False indica que el like fue removido
        else:
            self.likes.add(user)
            return True  # True indica que el like fue añadido

    def contributions(self):
        # No añadimos contributions como un campo del modelo, por tanto no se guarda en la base de datos. Lo calculamos cada vez que se llama a este método.
        # Intentamos obtener el formulario asociado con este proyecto.
        try:
            field_form = self.fieldform
            # Devolvemos el número de observaciones asociadas con este formulario.
            return field_form.observations.count()
        except Project.fieldform.RelatedObjectDoesNotExist:
            # Si no hay formulario asociado, devolvemos 0.
            return 0

# Modelo para asociar imágenes a un proyecto (Covers para el frontend)       
class ProjectCover(models.Model):
    project = models.ForeignKey(Project, related_name="covers", on_delete=models.CASCADE)
    image = models.ImageField(upload_to='projects/covers/', null=True, blank=True)

    def __str__(self):
        return f"Cover for {self.project.name}"