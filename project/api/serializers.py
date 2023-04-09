from rest_framework import serializers
from rest_framework.authtoken.models import Token

from django.contrib.auth.models import User
from project.models import Project, Topic, HasTag

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ['id', 'username']
        extra_kwargs = {'password': {'write_only': True, 'required': True}}

class ProjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = '__all__'

class TopicsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'

class HasTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = HasTag
        fields = '__all__'

class ProjectSerializerCreateUpdate(serializers.ModelSerializer):
    hasTag = serializers.PrimaryKeyRelatedField(
        queryset=HasTag.objects.all(),
        many=True,
        required=True)
    topic = serializers.PrimaryKeyRelatedField(
        queryset=Topic.objects.all(),
        many=True,
        required=True)

    class Meta:
        model = Project
        fields = '__all__'

    def create(self, validated_data, *args, **kwargs):
        hasTag = validated_data.pop('hasTag')
        topic = validated_data.pop('topic')

        project = Project.objects.create(**validated_data)
        for tag in hasTag:
            project.hasTag.add(tag)
        for topic in topic:
            project.topic.add(topic)
        return project


    def update(self, instance, validated_data):
        hasTag = validated_data.pop('hasTag')
        topic = validated_data.pop('topic')
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        instance.save()
        for tag in hasTag:
            instance.hasTag.add(tag)
        for topic in topic:
            instance.topic.add(topic)
        return instance


class ProjectSerializer(serializers.ModelSerializer):
    hasTag = HasTagSerializer(many=True)
    topic = TopicsSerializer(many=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'topic', 'hasTag', 'field_form']



        
