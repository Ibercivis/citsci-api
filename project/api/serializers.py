from rest_framework import serializers

from project.models import Project, Topic

class ProjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = '__all__'

class TopicsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'
        
