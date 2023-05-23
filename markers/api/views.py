import json
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from markers.models import Observation, ObservationImage
from markers.api.serializers import ObservationSerializer
from field_forms.models import FieldForm, Question

class ObservationListCreate(generics.ListCreateAPIView):
    queryset = Observation.objects.all()
    serializer_class = ObservationSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        field_form_id = request.data.get("field_form", None)
        if not field_form_id:
            return Response({"error": "No se proporcionó el formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            field_form = FieldForm.objects.get(pk=field_form_id)
        except FieldForm.DoesNotExist:
            return Response({"error": f"No existe un formulario de campo con id {field_form_id}."}, status=status.HTTP_400_BAD_REQUEST)

        print("request.FILES:", request.FILES) #Verificar que se reciben las imágenes
        data = request.data.get("data", {})

        # Intentar parsear data a un diccionario si es una cadena de texto
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return Response({"error": "La propiedad 'data' debería ser un objeto JSON válido."}, status=status.HTTP_400_BAD_REQUEST)

        # Asegurar que todas las claves en data se corresponden con ids de Pregunta en el FieldForm
        for question_id in data.keys():
            if not field_form.questions.filter(pk=question_id).exists():
                return Response({"error": f"No existe una pregunta con id {question_id} en este formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)

        timestamp = request.data.get("timestamp", None)
        geoposition = request.data.get("geoposition", None)

        # Almacena la pregunta y la imagen sin crear una instancia de ObservationImage aún
        image_files = []
        for question_id, image in request.FILES.items():
            print("Validating image question_id:", question_id) #Verificar que se reciben las imágenes
            try:
                question = field_form.questions.get(pk=question_id)
                if question.answer_type != Question.IMAGE:
                    return Response({"error": f"La pregunta {question_id} no es del tipo 'Imagen'."}, status=status.HTTP_400_BAD_REQUEST)
                # Almacenamos la pregunta y la imagen para más tarde
                image_files.append((question, image))
            except Question.DoesNotExist:
                return Response({"error": f"No existe una pregunta con id {question_id} en este formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)

        # Creamos la observación
        observation = Observation.objects.create(creator=request.user, field_form=field_form, timestamp=timestamp, geoposition=geoposition, data=data)

        # Ahora que la observación ha sido creada, creamos, validamos y guardamos nuestras imágenes
        for question, image in image_files:
            img = ObservationImage(observation=observation, image=image, question=question)
            try:
                img.full_clean()  # Validamos la imagen ahora que tenemos una observación
                img.save()
            except ValidationError as e:
                return Response({"error": f"Error al guardar la imagen para la pregunta {question_id}: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(observation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
class ObservationRetrieveUpdateDestroy(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    queryset = Observation.objects.all()
    serializer_class = ObservationSerializer

    def delete(self, request, *args, **kwargs):
        observation = self.get_object()
        if observation.creator != request.user:
            return Response({"error": "No tienes permiso para eliminar esta observación."}, status=status.HTTP_403_FORBIDDEN)

        observation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    def update(self, request, *args, **kwargs):
        observation = self.get_object()
        if not observation.creator == request.user:
            return Response({"error": "No tienes permiso para actualizar esta observación."}, status=status.HTTP_403_FORBIDDEN)

        # Continuar con la actualización
        return super().update(request, *args, **kwargs)

class ObservationByFieldFormList(generics.ListAPIView):
    serializer_class = ObservationSerializer

    def get_queryset(self):
        """
        Filtra las observaciones por field_form id.
        """
        field_form_id = self.kwargs['field_form_id']
        return Observation.objects.filter(field_form__id=field_form_id)
