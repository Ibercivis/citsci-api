from rest_framework import serializers
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from project.models import Project, Topic, HasTag, ProjectCover
from organizations.models import Organization
from organizations.api.serializers import OrganizationSerializer
from field_forms.models import FieldForm, Question
from field_forms.api.serializers import FieldFormSerializer, QuestionSerializer

import json


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

class ProjectCoverSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(use_url=True)

    class Meta:
        model = ProjectCover
        fields = ['image']

class ProjectSerializerCreateUpdate(serializers.ModelSerializer):
    hasTag = serializers.PrimaryKeyRelatedField(
        queryset=HasTag.objects.all(),
        many=True,
        required=False)
    topic = serializers.PrimaryKeyRelatedField(
        queryset=Topic.objects.all(),
        many=True,
        required=False)
    cover = ProjectCoverSerializer(required=False)
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
    is_liked_by_user = serializers.SerializerMethodField()
    is_private = serializers.BooleanField(required=False, default=False)
    raw_password = serializers.CharField(write_only=True, required=False, allow_blank=True, source="password")  # Usamos un campo virtual para la contraseña en texto plano.


    #NUEVALINEA (Si funciona la creación simultánea de Field_forms y Questions, borramos el comentario)
    field_form = FieldFormSerializer(required=False)
    

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'created_at', 'updated_at', 'topic', 'hasTag', 'cover', 'contributions', 'total_likes', 'is_liked_by_user', 'organizations', 'organizations_write', 'creator', 'administrators', 'is_private', 'raw_password', 'field_form']

    def validate(self, data):
        print("Contenido a validar del frontend:", data)
        if data.get("is_private") and not data.get("password"):
            raise serializers.ValidationError("Debe proporcionar una contraseña si el proyecto es privado.")
        return data
   
   # Este método verifica si el usuario actual ha dado "like" al proyecto. Utiliza el context del serializador para obtener el usuario actual.
    def get_is_liked_by_user(self, obj):
        user = self.context.get('user')
        if user and user.is_authenticated:
            liked = obj.likes.filter(id=user.id).exists()
            return liked
        return False
    
    # Este método nos permite personalizar la representación de las organizaciones para operaciones de lectura
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['organizations'] = OrganizationSummarySerializer(instance.organizations.all(), many=True).data
        representation['cover'] = ProjectCoverSerializer(instance.covers.all(), many=True).data
        return representation
    
    def create(self, validated_data, *args, **kwargs):
        print("Contenido validado del frontend para crear proyecto:",validated_data)
        hasTag = validated_data.pop('hasTag', [])
        topic = validated_data.pop('topic', [])
        administrators = validated_data.pop('administrators', [])
        organizations_write = validated_data.pop('organizations', [])
        cover_file = validated_data.pop('cover', None)
        #NUEVALINEA (Si funciona la creación simultánea de Field_forms y Questions, borramos el comentario)
        field_form_data = validated_data.pop('field_form', None)
        is_private = validated_data.pop('is_private', False)

        project = Project.objects.create(**validated_data)
        for tag in hasTag:
            project.hasTag.add(tag)
        for topic in topic:
            project.topic.add(topic)
        project.organizations.set(organizations_write)
        project.administrators.set(administrators)

        if cover_file:
            cover = self.context['request'].FILES.get('cover')
            ProjectCover.objects.create(project=project, image=cover)
        project.save()
        
        if "password" in validated_data:
            project.is_private = is_private
            password = validated_data.pop('password')
            project.password = password # Usamos el setter de la propiedad password para almacenar la contraseña encriptada
            project.save()

        if field_form_data:
            print("Entra en field_form_data: ", field_form_data)
            # Asegurarse de que field_form_data es un diccionario
            if isinstance(field_form_data, str):
                print("Es un string")
                try:
                    field_form_data = json.loads(field_form_data)
                except json.JSONDecodeError:
                    raise serializers.ValidationError({'field_form': ['Datos JSON inválidos.'] })
            # Crea el FieldForm asociado
            field_form = FieldForm.objects.create(project=project)
            print("FieldForm creado: ", field_form)
            for question_data in field_form_data.get('questions', []):
                print("Preguntas asociadas: ", question_data)
                Question.objects.create(field_form=field_form, **question_data)
            
            field_form.save()
        return project


    def update(self, instance, validated_data):
        user = self.context['request'].user
        new_hasTag = validated_data.pop('hasTag', [])
        new_topic = validated_data.pop('topic', [])
        creator = validated_data.pop('creator', None)
        administrators = validated_data.pop('administrators', [])
        organizations_write = validated_data.pop('organizations', [])
        cover_file = self.context['request'].FILES.get('cover')
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        instance.is_private = validated_data.get('is_private', instance.is_private)

        # Eliminar los temas y etiquetas existentes
        instance.hasTag.clear()
        instance.topic.clear()
        # Añadir los nuevos temas y etiquetas proporcionados en la llamada PATCH
        for tag in new_hasTag:
            instance.hasTag.add(tag)
        for topic in new_topic:
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

        if "password" in validated_data:
            password = validated_data.pop('password')
            instance.password = password
            instance.save()
        
        if cover_file:
            # Borramos las portadas anteriores
            instance.covers.all().delete()
            # Creamos las nuevas portadas
            cover = self.context['request'].FILES.get('cover')
            ProjectCover.objects.create(project=instance, image=cover)

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
