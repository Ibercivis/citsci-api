from rest_framework import serializers
from markers.models import Observation
from field_form.models import FieldForm
from django.core.files.images import get_image_dimensions

class DataFieldSerializer(serializers.JSONField):
    def to_internal_value(self, data):
        field_form = self.context.get("field_form", None)
        if not field_form:
            raise serializers.ValidationError("No se pudo encontrar la FieldForm relacionada.")
        
        # Validar los datos en función del tipo de respuesta
        for question, answer in data.items():
            question_obj = field_form.questions.get(pk=question)
            if question_obj.response_type == "DATE":
                try:
                    serializers.DateField().to_internal_value(answer)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser una fecha válida.")
            elif question_obj.response_type == "NUMBER":
                try:
                    serializers.DecimalField(max_digits=20, decimal_places=2).to_internal_value(answer)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser un número válido.")
            elif question_obj.response_type == "STRING":
                try:
                    serializers.CharField().to_internal_value(answer)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser un string válida.")
            elif question_obj.response_type == "IMAGE":
                # La validación de las imágenes se realizará en la vista
                pass
            else:
                raise serializers.ValidationError("Tipo de respuesta no válido.")
        return data

class ObservationSerializer(serializers.ModelSerializer):
    data = DataFieldSerializer()

    class Meta:
        model = Observation
        fields = ['id', 'field_form', 'timestamp', 'geoposition', 'data', 'created_at', 'updated_at']