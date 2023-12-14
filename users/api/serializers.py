from rest_framework import serializers, generics
from django.contrib.auth.models import User
from users.models import Profile
from organizations.models import Organization
from markers.models import Observation
from project.models import Project
from django_countries.fields import Country
from django_countries import countries

class ProjectSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'name', 'description']

class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'principalName']

class CustomCountryFieldSerializer(serializers.Field):
    def to_representation(self, value):
        country_code = str(value)  # Convertir el valor directamente a un string.
        country_name = dict(countries).get(country_code, country_code)
        return {
            "code": country_code,
            "name": country_name
        }
    
    def to_internal_value(self, data):
        # Aquí, data es el valor proporcionado en la solicitud (por ejemplo, "US" para Estados Unidos).
        # Este valor se convierte en el formato de `django-countries`.
        try:
            country = Country(data)  # Esto crea un objeto Country a partir del código de país.
        except Exception as e:
            raise serializers.ValidationError("Código de país no válido.")
        
        return country.code  # Devuelve el código de país para guardarlo en la base de datos.

class ProfileSerializer(serializers.ModelSerializer):
    created_organizations = serializers.SerializerMethodField()
    admin_organizations = serializers.SerializerMethodField()
    member_organizations = serializers.SerializerMethodField()
    participated_projects = serializers.SerializerMethodField()
    created_projects = serializers.SerializerMethodField()
    liked_projects = serializers.SerializerMethodField()
    country = CustomCountryFieldSerializer()
    cover = serializers.ImageField(required=False)

    class Meta:
        model = Profile
        fields = ['biography', 'visibility', 'country', 'cover', 'created_organizations', 'admin_organizations', 'member_organizations', 'participated_projects', 'created_projects', 'liked_projects']

    def get_admin_organizations(self, obj):
        organizations = Organization.objects.filter(administrators__in=[obj.user])
        return OrganizationSummarySerializer(organizations, many=True).data
    
    def get_member_organizations(self, obj):
        organizations = Organization.objects.filter(members__in=[obj.user])
        return OrganizationSummarySerializer(organizations, many=True).data
    
    def get_created_organizations(self, obj):
        organizations = Organization.objects.filter(creator=obj.user)
        return OrganizationSummarySerializer(organizations, many=True).data

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