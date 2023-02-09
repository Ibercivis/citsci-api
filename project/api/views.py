from rest_framework import viewsets
from project.models import Project, Topic
from project.api.serializers import ProjectsSerializer, TopicsSerializer

class ProjectsViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectsSerializer

class TopicsViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicsSerializer