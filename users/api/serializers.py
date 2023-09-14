from rest_framework import serializers, generics
from django.contrib.auth.models import User
from users.models import Profile
from organizations.models import Organization
from markers.models import Observation
from project.models import Project
from django_countries.fields import Country

class ProjectSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'name', 'description']

class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'principalName']

class CustomCountryFieldSerializer(serializers.Field):
    def to_representation(self, obj):
            # Aquí serializamos el campo `country` para obtener el código del país.
            if isinstance(obj, Country):
                return obj.name
            return obj  # Devuelve tal cual si no es una instancia de Country

class ProfileSerializer(serializers.ModelSerializer):
    created_organizations = OrganizationSummarySerializer(many=True, read_only=True)
    admin_organizations = OrganizationSummarySerializer(many=True, read_only=True)
    member_organizations = OrganizationSummarySerializer(many=True, read_only=True)
    participated_projects = serializers.SerializerMethodField()
    created_projects = serializers.SerializerMethodField()
    liked_projects = serializers.SerializerMethodField()
    country = CustomCountryFieldSerializer()

    class Meta:
        model = Profile
        fields = ['biography', 'visibility', 'country', 'created_organizations', 'admin_organizations', 'member_organizations', 'participated_projects', 'created_projects', 'liked_projects']

    def get_participated_projects(self, obj):
        # Aquí, 'obj' es una instancia de Profile, pero como Profile está relacionado
        # con User (ya que Profile tiene una relación OneToOne con User), podemos acceder
        # al usuario a través de obj.user
        project_ids = Observation.objects.filter(creator=obj.user).values_list('field_form__project', flat=True).distinct()
        projects = Project.objects.filter(id__in=project_ids)
        return ProjectSummarySerializer(projects, many=True).data
    
    def get_created_projects(self, obj): 
        projects = Project.objects.filter(creator=obj.user)
        return ProjectSummarySerializer(projects, many=True).data
    
    def get_liked_projects(self, obj):
        return ProjectSummarySerializer(obj.user.liked_projects.all(), many=True).data


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()

    class Meta:
        model = User
        fields = ['id', 'username', 'profile']
        extra_kwargs = {'password': {'write_only': True, 'required': True}}