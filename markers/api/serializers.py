from rest_framework import serializers
from markers.models import Marker, Answer

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ['id', 'marker', 'question', 'answer_text']

class MarkerSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, read_only=True)

    class Meta:
        model = Marker
        fields = ['id', 'field_form', 'latitude', 'longitude', 'answers']