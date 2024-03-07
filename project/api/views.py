from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import json
from django.contrib.auth.models import User
from project.models import ProjectCover

from project.models import Project, Topic, HasTag
from project.api.serializers import ProjectsSerializer, ProjectSerializerCreateUpdate, TopicsSerializer, HasTagSerializer, ProjectSerializer, UserSerializer

class ProjectsViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectsSerializer

class TopicsViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicsSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

class HasTagViewSet(viewsets.ModelViewSet):
    queryset = HasTag.objects.all()
    serializer_class = HasTagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

# Método de Fran. TODO: ¿eliminarlo?

class IsCreatorOrAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == 'DELETE':
            return obj.creator == request.user
        return obj.creator == request.user or request.user in obj.administrators.all()

class ProjectCreateViewSet(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, format=None):
        print("Contenido que entra desde frontend para crear proyecto:", request.data)

        # Extraer y procesar field_form si está presente y es un string
        field_form_data = request.data.get('field_form')
        if field_form_data and isinstance(field_form_data, str):
            try:
                field_form_data = json.loads(field_form_data)
                # Ahora puedes pasar el field_form_data procesado junto con otros datos al serializador
            except json.JSONDecodeError as e:
                return Response({'field_form': ['Datos JSON inválidos.']}, status=status.HTTP_400_BAD_REQUEST)

        # Crear un nuevo dict con los datos procesados
        data = {
            **request.data,
            'field_form': field_form_data  # Asegúrate de que esto es un dict y no un string
        }
        
        # Convertir los campos strings a los tipos correctos
        for field in ['name', 'description', 'raw_password']:
            if isinstance(data.get(field), list):
                data[field] = data.get(field)[0]
        # Asegúrate de que el 'creator' es un único valor, no una lista.
        if isinstance(data.get('creator'), list):
            data['creator'] = data.get('creator')[0]

        # Convierte 'is_private' a booleano.
        is_private = data.get('is_private')

        # Si is_private es una lista, toma el primer elemento
        if isinstance(is_private, list) and is_private:
            is_private = is_private[0]

        #Si is_private es true, se pinta privado, si no, público
        if is_private in ['true', 'True', '1', True]:
            data['is_private'] = True
        else:
            data['is_private'] = False

        # Agregar archivos al dict de datos
        if 'cover' in request.FILES:
            print("Se ha encontrado cover en los archivos")
            cover_file = request.FILES['cover']
            data['cover'] = {'image': cover_file}
        
        
        serializer = ProjectSerializerCreateUpdate(
            data=data, context={'request': request})
        if serializer.is_valid():
            project = serializer.save()
            """
            # Procesar los archivos de cover si están presentes
            if 'cover' in request.FILES:
                for file in request.FILES.getlist('cover'):
                    ProjectCover.objects.create(project=project, image=file)
            """
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        print(serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
   
class ProjectListCreate(generics.ListCreateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializerCreateUpdate
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_context(self):
        return {'user': self.request.user}

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectRetrieveUpdateDestroy(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializerCreateUpdate
    permission_classes = [IsCreatorOrAdminOrReadOnly]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_serializer_context(self):
        """
        Sobrescribe el método para asegurarse de que el contexto incluya el usuario.
        """
        """
        context = super().get_serializer_context()
        context.update({"user": self.request.user})
        return context
        """
        return {'user': self.request.user}

    def update(self, request, *args, **kwargs):
        print("LLamada al editar un proyecto", request.data)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
class ValidateProjectPasswordView(APIView):
    
    def post(self, request, project_id):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return Response({'detail': 'Proyecto no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        password = request.data.get('password')
        if not password:
            return Response({'detail': 'Contraseña no proporcionada.'}, status=status.HTTP_400_BAD_REQUEST)

        if project.check_password(password):
            return Response({'valid': True}, status=status.HTTP_200_OK)
        else:
            return Response({'valid': False, 'detail': 'Contraseña incorrecta.'}, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_project_like(request, project_id):
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        was_liked = project.toggle_like(request.user)
        action = "added" if was_liked else "removed"
        return Response({"message": f"Like {action} successfully", "total_likes": project.total_likes})