from rest_framework import serializers
from organizations.models import Organization, Type
from django.contrib.auth.models import User
from users.api.serializers import UserSerializer

class TypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Type
        fields = '__all__'

class OrganizationSerializer(serializers.ModelSerializer):
    type = TypeSerializer(many=True, read_only=True)
    creator = UserSerializer(read_only=True)
    administrators = UserSerializer(many=True, read_only=True)
    members = UserSerializer(many=True, read_only=True)
    class Meta:
        model = Organization
        fields = '__all__'

class OrganizationSerializerCreateUpdate(serializers.ModelSerializer):
    type = serializers.PrimaryKeyRelatedField(
        queryset=Type.objects.all(),
        many=True,
        required=False)
    creator = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=True)
    administrators = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False)
    members = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False)
    logo = serializers.ImageField(required=False)
    cover = serializers.ImageField(required=False)

    class Meta:
        model = Organization
        fields = '__all__'

    def create(self, validated_data, *args, **kwargs):
        type = validated_data.pop('type')
        administrators_data = validated_data.pop('administrators', [])
        members_data = validated_data.pop('members', [])

        organization = Organization.objects.create(**validated_data)
        for type in type:
            organization.type.add(type)

        if administrators_data:
            organization.administrators.set(administrators_data)
        if members_data:
            organization.members.set(members_data)

        organization.save()
        return organization

    def update(self, instance, validated_data):
        type = validated_data.pop('type', None) # Añade un valor predeterminado None
        creator_data = validated_data.pop('creator', None)
        administrators_data = validated_data.pop('administrators', None)
        members_data = validated_data.pop('members', None)

        instance.principalName = validated_data.get('principalName', instance.principalName)
        instance.url = validated_data.get('url', instance.url)
        instance.description = validated_data.get('description', instance.description)
        instance.contactName = validated_data.get('contactName', instance.contactName)
        instance.contactMail = validated_data.get('contactMail', instance.contactMail)
        instance.logo = validated_data.get('logo', instance.logo)
        instance.cover = validated_data.get('cover', instance.cover)
        
        #for type in type:
        #    instance.type.add(type)
        if type is not None:  # Solo actualiza el campo 'type' si está presente en la solicitud
            instance.type.set(type)

        if creator_data and self.context['request'].user == instance.creator:
            instance.creator = creator_data

        if administrators_data:
            instance.administrators.set(administrators_data)

        if members_data:
            instance.members.set(members_data)
    
        instance.save()
        
        return instance