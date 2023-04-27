from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics

from django.contrib.auth.models import User
from users.api.serializers import UserSerializer

class UserViewSet(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class UserViewSetDetail(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer