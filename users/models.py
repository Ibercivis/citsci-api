from django.db import models
from django.contrib.auth.models import User
from django_countries.fields import CountryField 

# Create your models here.

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    biography = models.TextField(blank=True, null=True)
    visibility = models.BooleanField(default=True)
    country = CountryField()  # Empleamos la librería `django-countries`.
    cover = models.ImageField(upload_to='users/covers/', null=True, blank=True)

    def __str__(self):
        return self.user.username
