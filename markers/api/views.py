from django.core.files.uploadedfile import InMemoryUploadedFile

# ...

class ObservationListCreate(generics.ListCreateAPIView):
    queryset = Observation.objects.all()
    serializer_class = ObservationSerializer

    def create(self, request, *args, **kwargs):
        field_form_id = request.data.get("field_form", None)
        field_form = None
        if field_form_id:
            try:
                field_form = FieldForm.objects.get(pk=field_form_id)
            except FieldForm.DoesNotExist:
                pass
        
        serializer = self.get_serializer(data=request.data, context={"field_form": field_form})
        
        # Validar y almacenar las imágenes
        data_with_images = request.data.get("data", {}).copy()
        for question, answer in request.data.get("data", {}).items():
            question_obj = field_form.questions.get(pk=question)
            if question_obj.response_type == "IMAGE":
                # Asegurarse de que la respuesta es una imagen válida
                uploaded_file = request.FILES.get(f"data_{question}", None)
                if not uploaded_file or not isinstance(uploaded_file, InMemoryUploadedFile) or not get_image_dimensions(uploaded_file):
                    return Response({"error": f"La respuesta para la pregunta {question} debe ser una imagen válida."},
                                    status=status.HTTP_400_BAD_REQUEST)
                # Almacenar la imagen
                # Aquí puedes almacenar la imagen de la manera que prefieras, como en un directorio específico o en un servicio de almacenamiento en la nube (AWS S3, Google Cloud Storage, etc.)
                # Por ahora, solo guardaremos la ruta de la imagen en el campo JSON
                image_path = f"images/{uploaded_file.name}"
                uploaded_file.save(image_path)
                data_with_images[question] = image_path
        
        serializer = self.get_serializer(data={**request.data, "data": data_with_images}, context={"field_form": field_form})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)