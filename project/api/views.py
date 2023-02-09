from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from project.models import Project, Topic, HasTag
from project.api.serializers import ProjectsSerializer, TopicsSerializer, HasTagSerializer, ProjectSerializerCreateUpdate

class ProjectsViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectsSerializer

class TopicsViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicsSerializer

class HasTagViewSet(viewsets.ModelViewSet):
    queryset = HasTag.objects.all()
    serializer_class = HasTagSerializer

class ProjectCreateViewSet(APIView):

    def post(self, request, format=None):
        serializer = ProjectSerializerCreateUpdate(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)