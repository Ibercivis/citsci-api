from django.db import models
from django.contrib.auth.models import User


# Create your models here.
class Type(models.Model):
    type = models.TextField()

    def __str__(self):
        return f'{self.type}'

class Organization(models.Model):
    principalName = models.CharField(max_length=50, blank=False)
    url = models.CharField(max_length=50, blank=True)
    description = models.CharField(max_length=500, blank=True)
    type = models.ManyToManyField(Type, blank=True)
    contactName = models.CharField(max_length=50, blank=True)
    contactMail = models.CharField(max_length=50, blank=True)
    logo = models.ImageField(upload_to='organizations/logos/', null=True, blank=True)
    cover = models.ImageField(upload_to='organizations/covers/', null=True, blank=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_organizations", null=True, blank=True) # REVISAR EL NULL Y BLANK
    administrators = models.ManyToManyField(User, related_name="admin_organizations", blank=True)
    members = models.ManyToManyField(User, related_name="member_organizations", blank=True)