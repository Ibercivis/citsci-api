from rest_framework import serializers
from rest_framework.authtoken.models import Token

from django.contrib.auth.models import User
from project.models import Project, Topic, HasTag
from organizations.models import Organization
from organizations.api.serializers import OrganizationSerializer

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
        required=False)
    topic = serializers.PrimaryKeyRelatedField(
        queryset=Topic.objects.all(),
        many=True,
        required=False)
    organizations = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(),
        many=True,
        required=False)
    creator = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False)
    administrators = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False)
    

    class Meta:
        model = Project
        fields = '__all__'

    def create(self, validated_data, *args, **kwargs):
        hasTag = validated_data.pop('hasTag', [])
        topic = validated_data.pop('topic', [])
        administrators = validated_data.pop('administrators', [])
        organizations = validated_data.pop('organizations', [])

        project = Project.objects.create(**validated_data)
        for tag in hasTag:
            project.hasTag.add(tag)
        for topic in topic:
            project.topic.add(topic)
        project.organizations.set(organizations)
        project.administrators.set(administrators)
        project.save()
        return project


    def update(self, instance, validated_data):
        user = self.context['request'].user
        hasTag = validated_data.pop('hasTag', [])
        topic = validated_data.pop('topic', [])
        creator = validated_data.pop('creator', None)
        administrators = validated_data.pop('administrators', [])
        organizations = validated_data.pop('organizations', [])
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        for tag in hasTag:
            instance.hasTag.add(tag)
        for topic in topic:
            instance.topic.add(topic)
        if creator:
            if user == instance.creator:
                instance.creator = creator
            else:
                raise serializers.ValidationError("Solo el creador puede cambiar el campo 'creator'.")
        if administrators:
            instance.administrators.set(administrators)

        if organizations:
            instance.organizations.set(organizations)
        #instance.organizations.set(organizations)
        #instance.administrators.set(administrators)
        #if 'creator' in validated_data and validated_data['creator'] != instance.creator:
        #    if user != instance.creator:
        #        raise serializers.ValidationError("Solo el creador puede cambiar el campo 'creator'.")
        instance.save()    
        return instance


class ProjectSerializer(serializers.ModelSerializer):
    hasTag = HasTagSerializer(many=True)
    topic = TopicsSerializer(many=True)
    organizations = OrganizationSerializer(many=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'created_at', 'updated_at', 'topic', 'hasTag', 'organizations', 'creator', 'administrators']



        
