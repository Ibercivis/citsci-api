import json, csv
from django.http import HttpResponse
from rest_framework.views import View
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

        print("Llamada al crear:", request.data) #Verificar que se reciben las imágenes

        data = request.data.get("data", [])

        # Intentar parsear data a una lista si es una cadena de texto
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return Response({"error": "La propiedad 'data' debería ser una lista JSON válida."}, status=status.HTTP_400_BAD_REQUEST)

        for item in data:
            if "key" not in item or "value" not in item:
                return Response({"error": "Cada ítem en 'data' debe contener un 'key' y un 'value'."}, status=status.HTTP_400_BAD_REQUEST)

        # Convertir data a un diccionario para facilitar la validación
        data_dict = {item["key"]: item["value"] for item in data}

        # Asegurar que todas las claves en data_dict se corresponden con ids de Pregunta en el FieldForm
        for question_id in data_dict.keys():
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

        # Preparamos todo lo necesario para el proceso de validacion en el serializer

        # Recolectar IDs de preguntas de imagen
        image_question_ids = [key for key in request.FILES.keys()]

        # Crear un diccionario de datos con los campos necesarios
        observation_data = {
            'creator': request.user.id,
            'field_form': field_form.id,
            'timestamp': timestamp,
            'geoposition': geoposition,
            'data': data,
        }

        # Crear el serializador con los datos y el contexto
        serializer = ObservationSerializer(data=observation_data, context={"field_form": field_form, "image_question_ids": image_question_ids})
        if serializer.is_valid(raise_exception=True):
            # Guardar la observación si es válida
            observation = serializer.save()

            # Ahora que la observación ha sido creada, creamos, validamos y guardamos nuestras imágenes
            for question, image in image_files:
                img = ObservationImage(observation=observation, image=image, question=question)
                try:
                    img.full_clean()  # Validamos la imagen ahora que tenemos una observación
                    img.save()
                except ValidationError as e:
                    return Response({"error": f"Error al guardar la imagen para la pregunta {question_id}: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

            # Devolver 201 con la observación creada
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class ObservationRetrieveUpdateDestroy(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    queryset = Observation.objects.all()
    serializer_class = ObservationSerializer
    parser_classes = (MultiPartParser, FormParser)

    def delete(self, request, *args, **kwargs):
        observation = self.get_object()
        if observation.creator != request.user:
            return Response({"error": "No tienes permiso para eliminar esta observación."}, status=status.HTTP_403_FORBIDDEN)

        observation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    def update(self, request, *args, **kwargs):
        print("Llamada al actualizar:", request.data)  # Verificar que se reciben las imágenes

        observation = self.get_object()
        if not observation.creator == request.user:
            return Response({"error": "No tienes permiso para actualizar esta observación."}, status=status.HTTP_403_FORBIDDEN)
        
        # Obtener el field_form_id y el objeto FieldForm
        field_form_id = request.data.get("field_form", None)
        if not field_form_id:
            return Response({"error": "No se proporcionó el formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            field_form = FieldForm.objects.get(pk=field_form_id)
        except FieldForm.DoesNotExist:
            return Response({"error": f"No existe un formulario de campo con id {field_form_id}."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Obtener data y validarla
        data = request.data.get("data", [])

        # Intentar parsear data a una lista si es una cadena de texto
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return Response({"error": "La propiedad 'data' debería ser una lista JSON válida."}, status=status.HTTP_400_BAD_REQUEST)

        for item in data:
            if "key" not in item or "value" not in item:
                return Response({"error": "Cada ítem en 'data' debe contener un 'key' y un 'value'."}, status=status.HTTP_400_BAD_REQUEST)

        # Convertir data a un diccionario para facilitar la validación
        data_dict = {item["key"]: item["value"] for item in data}

        # Asegurar que todas las claves en data_dict se corresponden con ids de Pregunta en el FieldForm
        for question_id in data_dict.keys():
            if not field_form.questions.filter(pk=question_id).exists():
                return Response({"error": f"No existe una pregunta con id {question_id} en este formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)

        # Manejar imágenes: 
        # 1. Verificar las imágenes que se envían en la solicitud.
        # 2. Si una imagen ya existe para una pregunta y se envía una nueva, reemplazarla.
        # 3. Si no se envía una imagen para una pregunta que ya tenía una, conservar la anterior.
        image_files = []
        for question_id, image in request.FILES.items():
            try:
                question = field_form.questions.get(pk=question_id)
                if question.answer_type != Question.IMAGE:
                    return Response({"error": f"La pregunta {question_id} no es del tipo 'Imagen'."}, status=status.HTTP_400_BAD_REQUEST)
                # Si ya hay una imagen para esta pregunta, eliminarla
                existing_image = ObservationImage.objects.filter(observation=observation, question=question).first()
                if existing_image:
                    existing_image.image.delete()  # Elimina el archivo de imagen del sistema de archivos
                    existing_image.delete()  # Elimina el objeto de la base de datos
                # Almacenar la nueva imagen para guardarla después de la actualización
                image_files.append((question, image))
            except Question.DoesNotExist:
                return Response({"error": f"No existe una pregunta con id {question_id} en este formulario de campo."}, status=status.HTTP_400_BAD_REQUEST)

        # Recolectar IDs de preguntas de imagen para la Validación en el Serializer
        image_question_ids = [key for key in request.FILES.keys()]

        # Actualizar la observación
        serializer = self.get_serializer(observation, data=request.data, context={"field_form": field_form, "image_question_ids": image_question_ids})
        print(type(data), data)
        serializer.is_valid(raise_exception=True)
        print(serializer.errors)
        self.perform_update(serializer)

        # Guardar las nuevas imágenes
        for question, image in image_files:
            img = ObservationImage(observation=observation, image=image, question=question)
            try:
                img.full_clean()  # Validamos la imagen ahora que tenemos una observación
                img.save()
            except ValidationError as e:
                return Response({"error": f"Error al guardar la imagen para la pregunta {question_id}: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        if getattr(observation, '_prefetched_objects_cache', None):
            # Si se realiza 'prefetch_related()', debemos borrar el caché prefetch
            # para que las instancias cargadas previamente sean revalorizadas.
            observation._prefetched_objects_cache = {}

        return Response(serializer.data)

class ObservationByFieldFormList(generics.ListAPIView):
    serializer_class = ObservationSerializer

    def get_queryset(self):
        """
        Filtra las observaciones por field_form id.
        """
        field_form_id = self.kwargs['field_form_id']
        return Observation.objects.filter(field_form__id=field_form_id)
    
class DownloadObservationsCSV(View):
    def get(self, request, *args, **kwargs):
        project_id = self.kwargs.get("project_id")

        # Filtramos las observaciones por el field_form asociado al proyecto dado
        observations = Observation.objects.filter(field_form__project__id=project_id)

        # Preparamos la respuesta
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="project_{project_id}_observations.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', 'Creator', 'Timestamp', 'Geoposition', 'Data'])  # header

        for observation in observations:
            writer.writerow([observation.id, observation.creator, observation.timestamp, observation.geoposition, observation.data])

        return response 
