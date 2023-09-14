from rest_framework import serializers
from field_forms.models import FieldForm, Question
from project.models import Project

class QuestionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Question
        fields = ['id', 'question_text', 'answer_type']


class FieldFormSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True)
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), required=False)

    class Meta:
        model = FieldForm
        fields = ['id', 'project', 'questions']

    def create(self, validated_data):
        questions_data = validated_data.pop('questions')
        field_form = FieldForm.objects.create(**validated_data)
        for question_data in questions_data:
            Question.objects.create(field_form=field_form, **question_data)
        return field_form

    def update(self, instance, validated_data):
        questions_data = validated_data.pop('questions')
        instance.project = validated_data.get('project', instance.project)
        instance.save()

        current_question_ids = [q.id for q in instance.questions.all()]
        incoming_question_ids = [q.get('id') for q in questions_data if 'id' in q]

        # Delete questions that are not in the incoming data
        for question_id in current_question_ids:
            if question_id not in incoming_question_ids:
                Question.objects.get(id=question_id).delete()

        # Create or update questions
        for question_data in questions_data:
            question_id = question_data.get('id', None)
            if question_id in current_question_ids:
                # The question already exists, update it
                question = Question.objects.get(id=question_id)
                question.question_text = question_data.get('question_text', question.question_text)
                question.answer_type = question_data.get('answer_type', question.answer_type)
                question.save()
            else:
                # The question does not exist, create it
                Question.objects.create(field_form=instance, **question_data)

        return instance
