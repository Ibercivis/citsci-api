from rest_framework import serializers
from field_forms.models import FieldForm, Question

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ['id', 
                  'field_form', 
                  'question_text', 'answer_type']

class FieldFormSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True, source='question_set')

    class Meta:
        model = FieldForm
        fields = ['id', 'project', 'questions']

    def create(self, validated_data):
        questions_data = validated_data.pop('questions')
        field_form = FieldForm.objects.create(**validated_data)
        for question_data in questions_data:
            Question.objects.create(field_form=field_form, **question_data)
        return field_form 