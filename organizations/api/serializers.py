from rest_framework import serializers
from .models import Organization, Type

class TypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Type
        fields = '__all__'

class OrganizationSerializer(serializers.ModelSerializer):
    type = TypeSerializer(many=True, read_only=True)
    class Meta:
        model = Organization
        fields = '__all__'

class OrganizationSerializerCreateUpdate(serializers.ModelSerializer):
    type = serializers.PrimaryKeyRelatedField(
        queryset=Type.objects.all(),
        many=True,
        required=True)

    class Meta:
        model = Organization
        fields = '__all__'

    def create(self, validated_data, *args, **kwargs):
        type = validated_data.pop('type')

        organization = Organization.objects.create(**validated_data)
        for type in type:
            organization.type.add(type)
        return organization

    def update(self, instance, validated_data):
        type = validated_data.pop('type')
        instance.principalName = validated_data.get('principalName', instance.principalName)
        instance.url = validated_data.get('url', instance.url)
        instance.description = validated_data.get('description', instance.description)
        instance.contactName = validated_data.get('contactName', instance.contactName)
        instance.contactMail = validated_data.get('contactMail', instance.contactMail)
        instance.logo = validated_data.get('logo', instance.logo)
        instance.creditLogo = validated_data.get('creditLogo', instance.creditLogo)
        instance.save()
        for type in type:
            instance.type.add(type)
        return instance