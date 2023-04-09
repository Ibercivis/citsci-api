from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics

from django.contrib.auth.models import User

from organizations.models import Organization, Type
from .serializers import OrganizationSerializer, OrganizationSerializerCreateUpdate

class OrganizationViewSet(generics.ListAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

class TypeViewSet(generics.ListAPIView):
    queryset = Type.objects.all()
    serializer_class = OrganizationSerializer

class OrganizationCreateViewSet(APIView):

    def post(self, request, format=None):
        serializer = OrganizationSerializerCreateUpdate(
            data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)