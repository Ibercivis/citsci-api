from django.db import models

# Create your models here.
class Type(models.Model):
    type = models.TextField()

    def __str__(self):
        return f'{self.type}'

class Organization(models.Model):
    principalName = models.CharField(max_length=50, blank=False)
    url = models.CharField(max_length=50, blank=False)
    description = models.CharField(max_length=200, blank=False)
    type: models.ManyToManyField(Type, blank=True)
    contactName = models.CharField(max_length=50, blank=False)
    contactMail = models.CharField(max_length=50, blank=False)
    logo = models.CharField(max_length=200, blank=False)
    creditLogo = models.CharField(max_length=100, blank=False)