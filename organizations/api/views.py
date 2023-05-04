from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.permissions import SAFE_METHODS

from django.contrib.auth.models import User

from organizations.models import Organization, Type
from .serializers import OrganizationSerializer, OrganizationSerializerCreateUpdate, TypeSerializer

class IsOrganizationCreatorOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if request.method == "DELETE":
            return request.user == obj.creator

        return request.user == obj.creator or request.user in obj.administrators.all()

class OrganizationViewSet(generics.ListAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

class TypeViewSet(generics.ListAPIView):
    queryset = Type.objects.all()
    serializer_class = TypeSerializer

class OrganizationCreateViewSet(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        serializer = OrganizationSerializerCreateUpdate(
            data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class OrganizationDetailUpdateDelete(generics.RetrieveUpdateDestroyAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializerCreateUpdate
    permission_classes = [IsAuthenticated, IsOrganizationCreatorOrAdmin]