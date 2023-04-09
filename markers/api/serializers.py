from rest_framework import serializers
from markers.models import Marker, Answer
from field_forms.models import Question

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ['id', 'marker', 'question', 'value']

class MarkerSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, read_only=True)

    class Meta:
        model = Marker
        fields = ['id', 'field_form', 'latitude', 'longitude', 'answers']

        def create(self, validated_data):
            answers_data = validated_data.pop('answers')
            marker = Marker.objects.create(**validated_data)
            for answer_data in answers_data:
                question = Question.objects.get(pk=answer_data['question'].id)
                Answer.objects.create(marker=marker, question=question, **answer_data)
            return marker