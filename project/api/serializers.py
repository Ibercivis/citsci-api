from rest_framework import serializers
from rest_framework.authtoken.models import Token

from django.contrib.auth.models import User
from project.models import Project, Topic, HasTag
from organizations.models import Organization
from organizations.api.serializers import OrganizationSerializer
from field_forms.models import FieldForm, Question
from field_forms.api.serializers import FieldFormSerializer, QuestionSerializer


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ['id', 'username']
        extra_kwargs = {'password': {'write_only': True, 'required': True}}

class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'principalName']

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
    organizations = OrganizationSummarySerializer(many=True, read_only=True)
    organizations_write = serializers.PrimaryKeyRelatedField(
        source='organizations',  # Asignamos el comportamiento de escritura al campo real 'organizations'
        queryset=Organization.objects.all(),
        many=True,
        required=False,
        write_only=True  # Esto garantiza que este campo solo se utilice para escritura
    )
    creator = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False)
    administrators = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False)
    contributions = serializers.IntegerField(read_only=True)
    total_likes = serializers.IntegerField(read_only=True)

    #NUEVALINEA (Si funciona la creación simultánea de Field_forms y Questions, borramos el comentario)
    field_form = FieldFormSerializer(required=False)
    

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'created_at', 'updated_at', 'topic', 'hasTag', 'contributions', 'total_likes', 'organizations', 'organizations_write', 'creator', 'administrators', 'field_form']

    # Este método nos permite personalizar la representación de las organizaciones para operaciones de lectura
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['organizations'] = OrganizationSummarySerializer(instance.organizations.all(), many=True).data
        return representation
    
    def create(self, validated_data, *args, **kwargs):
        hasTag = validated_data.pop('hasTag', [])
        topic = validated_data.pop('topic', [])
        administrators = validated_data.pop('administrators', [])
        organizations_write = validated_data.pop('organizations', [])
        #NUEVALINEA (Si funciona la creación simultánea de Field_forms y Questions, borramos el comentario)
        field_form_data = validated_data.pop('field_form', None)

        project = Project.objects.create(**validated_data)
        for tag in hasTag:
            project.hasTag.add(tag)
        for topic in topic:
            project.topic.add(topic)
        project.organizations.set(organizations_write)
        project.administrators.set(administrators)
        project.save()
        #NUEVALINEA (Si funciona la creación simultánea de Field_forms y Questions, borramos el comentario)
        if field_form_data:
            # Crea el FieldForm asociado
            field_form = FieldForm.objects.create(project=project)
            for question_data in field_form_data.get('questions', []):
                Question.objects.create(field_form=field_form, **question_data)
            
            field_form.save()
        return project


    def update(self, instance, validated_data):
        user = self.context['request'].user
        hasTag = validated_data.pop('hasTag', [])
        topic = validated_data.pop('topic', [])
        creator = validated_data.pop('creator', None)
        administrators = validated_data.pop('administrators', [])
        organizations_write = validated_data.pop('organizations', [])
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

        if organizations_write:
            instance.organizations.set(organizations_write)
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
    contributions = serializers.IntegerField(source='contributions', read_only=True)
    total_likes = serializers.IntegerField(source='total_likes', read_only=True)


    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'created_at', 'updated_at', 'topic', 'hasTag', 'contributions', 'total_likes', 'organizations', 'creator', 'administrators']



        
