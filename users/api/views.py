from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics, permissions
from django_countries import countries
from django.contrib.auth.models import User
from users.api.serializers import UserSerializer
from users.models import Profile
from users.api.serializers import ProfileSerializer

class UserViewSet(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class UserViewSetDetail(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

#Vista para obtener los usuarios visibles
class VisibleUsersListView(generics.ListAPIView):
    serializer_class = UserSerializer

    def get_queryset(self):
        return User.objects.filter(profile__visibility=True)

class CountryListView(APIView):
    def get(self, request):
        return Response(list(countries))

class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]  # asegura que el usuario esté autenticado

    def get_object(self):
        # Obtiene el perfil del usuario actual
        return self.request.user.profile

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        serializer = self.get_serializer(self.object, data=request.data, partial=True)  # `partial=True` permite actualizaciones parciales (PATCH)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)