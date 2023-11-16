from rest_framework import serializers
from markers.models import Observation, ObservationImage
from field_forms.models import FieldForm

class DataFieldSerializer(serializers.JSONField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        # Asegurar que los datos tienen la estructura correcta
        if not isinstance(data, list):
            raise serializers.ValidationError("La estructura de datos no es una lista.")
        elif not all(['key' in item and 'value' in item for item in data]):
            raise serializers.ValidationError("La estructura de datos no tiene las claves 'key' y 'value'.")
        
        field_form = self.context.get("field_form", None)
        if not field_form:
            raise serializers.ValidationError("No se pudo encontrar la FieldForm relacionada.")
        
        # Convertir data a un diccionario para facilitar la validación de las preguntas que no son imágenes
        data_dict = {item["key"]: item["value"] for item in data}
        print("Data dict: ", data_dict)

        # Acceder al contexto para obtener los IDs de las preguntas que son imágenes
        image_question_ids = self.context.get('image_question_ids', [])

        # Acceder al contexto para verificar si es una creación o actualización
        observation_instance = self.context.get('instance', None)

        # Si es una creación, se realiza la validación completa
        if observation_instance is None:
            # Validar que se hayan respondido todas las preguntas obligatorias
            mandatory_questions = field_form.questions.filter(mandatory=True)
            print("Preguntas obligatorias de este proyecto", mandatory_questions)
            for question in mandatory_questions:
                if question.answer_type in ["IMAGE", "IMG"]:
                    if str(question.id) not in image_question_ids:
                        raise serializers.ValidationError(f"La pregunta {question} es obligatoria y no ha sido respondida.")
                else:
                    if str(question.id) not in data_dict:
                        raise serializers.ValidationError(f"La pregunta {question} es obligatoria y no ha sido respondida.")
        
        # Validar los datos en función del tipo de respuesta
        for key, value in data_dict.items():
            question_obj = field_form.questions.get(pk=key)
            print(f"Question ID: {key}, Answer Type: {question_obj.answer_type}, Value: {value}")  # DEBUG
            if question_obj.answer_type == "DATE":
                try:
                    serializers.DateField().to_internal_value(value)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser una fecha válida.")
            elif question_obj.answer_type == "NUMBER" or question_obj.answer_type == "NUM":
                try:
                    serializers.DecimalField(max_digits=20, decimal_places=2).to_internal_value(value)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser un número válido.")
            elif question_obj.answer_type == "STRING" or question_obj.answer_type == "STR":
                try:
                    serializers.CharField().to_internal_value(value)
                except serializers.ValidationError:
                    raise serializers.ValidationError(f"La respuesta para la pregunta {question} debe ser un string válida.")
            elif question_obj.answer_type == "IMAGE" or question_obj.answer_type == "IMG":
                # La validación de las imágenes se realizará en la vista
                pass
            else:
                raise serializers.ValidationError("Tipo de respuesta no válido.")
        return data
    
class ObservationImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(max_length=None, use_url=True)

    class Meta:
        model = ObservationImage
        fields = ['id', 'image', 'question']

class ObservationSerializer(serializers.ModelSerializer):
    data = DataFieldSerializer()
    images = ObservationImageSerializer(many=True, read_only=True)  # Inclusión de imágenes en la respuesta

    class Meta:
        model = Observation
        fields = ['id', 'creator', 'field_form', 'timestamp', 'geoposition', 'data', 'created_at', 'updated_at', 'images']