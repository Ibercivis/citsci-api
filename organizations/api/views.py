from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
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
    serializer_class = OrganizationSerializerCreateUpdate

class TypeViewSet(generics.ListAPIView):
    queryset = Type.objects.all()
    serializer_class = TypeSerializer

class OrganizationCreateViewSet(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, format=None):
        serializer = OrganizationSerializerCreateUpdate(
            data=request.data)
        print(request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        print(serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class OrganizationDetailUpdateDelete(generics.RetrieveUpdateDestroyAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializerCreateUpdate
    permission_classes = [IsOrganizationCreatorOrAdmin]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, *args, **kwargs):
        # Log del token que se está recibiendo
        auth_header = request.headers.get('Authorization', None)
        if auth_header:
            # Divides el prefijo del token si está presente.
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == 'Token':
                token = parts[1]
                print(f'Token recibido: {token}')
            else:
                print(auth_header)
        else:
            print('No se encontró el header de Authorization.')

        # Continúa con el procesamiento normal de la petición.
        return super().get(request, *args, **kwargs)
    