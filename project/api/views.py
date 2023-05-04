from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework import permissions

from django.contrib.auth.models import User

from project.models import Project, Topic, HasTag
from project.api.serializers import ProjectsSerializer, ProjectSerializerCreateUpdate, TopicsSerializer, HasTagSerializer, ProjectSerializer, UserSerializer

class ProjectsViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectsSerializer

class TopicsViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicsSerializer

class HasTagViewSet(viewsets.ModelViewSet):
    queryset = HasTag.objects.all()
    serializer_class = HasTagSerializer

# Método de Fran. TODO: ¿eliminarlo?

class IsCreatorOrAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == 'DELETE':
            return obj.creator == request.user
        return obj.creator == request.user or request.user in obj.administrators.all()

class ProjectCreateViewSet(APIView):

    def post(self, request, format=None):
        serializer = ProjectSerializerCreateUpdate(
            data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
   
class ProjectListCreate(generics.ListCreateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializerCreateUpdate

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectRetrieveUpdateDestroy(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializerCreateUpdate
    permission_classes = [IsCreatorOrAdminOrReadOnly]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)