from rest_framework import serializers
from field_forms.models import FieldForm, Question

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ['id', 'field_form', 'question_text', 'answer_type']

class FieldFormSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = FieldForm
        fields = ['id', 'project', 'questions']