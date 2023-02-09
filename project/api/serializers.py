from rest_framework import serializers

from project.models import Project, Topic, HasTag

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
        #read_only_fields = ('creator',)
        #extra_kwargs = {
        #    'creator': {'write_only': True}
        #}

    def create(self, validated_data):
        hasTag = validated_data.pop('hasTag')
        topic = validated_data.pop('topic')
        project = Project.objects.create(**validated_data)
        project.hasTag.set(hasTag)
        project.topic.set(topic)
        return project

    def update(self, instance, validated_data):
        hasTag = validated_data.pop('hasTag')
        topic = validated_data.pop('topic')
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        instance.save()
        instance.hasTag.set(hasTag)
        instance.topic.set(topic)
        return instance

class ProjectSerializer(serializers.ModelSerializer):
    hasTag = HasTagSerializer(many=True)
    topic = TopicsSerializer(many=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'topic', 'hasTag']

        
