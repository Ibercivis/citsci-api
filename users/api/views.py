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
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import requests
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.http import HttpResponse
from dj_rest_auth.registration.views import ConfirmEmailView

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
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_object(self):
        # Obtiene el perfil del usuario actual
        return self.request.user.profile

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        serializer = self.get_serializer(self.object, data=request.data, partial=True)  # `partial=True` permite actualizaciones parciales (PATCH)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        print(serializer.errors)
        return Response(serializer.errors, status=400)

class CustomConfirmEmailView(ConfirmEmailView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # Verifica si la confirmación fue exitosa
        if response.status_code == 302:  # 302 es un código de redirección
            return HttpResponse("Confirmación de correo electrónico exitosa.", status=200)
        else:
            return response


class ActivateAccountView(View):

    @method_decorator(csrf_exempt)
    def get(self, request, key):
        # Define la URL de la API para la activación
        api_url = 'http://dev.ibercivis.es:10001/api/users/registration/account-confirm-email/{key}/'.format(key=key)

        # Realiza la llamada POST al servidor para activar la cuenta
        response = requests.post(api_url, data={'key': key})

        # Comprueba la respuesta y muestra un mensaje adecuado al usuario
        if response.status_code == 200:
            # La cuenta ha sido activada
            return render(request, 'activation_success.html')
        else:
            # Algo salió mal, maneja el error
            return render(request, 'activation_fail.html', {'error': response.text})
"""
def activate_account(request, key):
    # Define la URL de la API para la activación
    api_url = 'http://dev.ibercivis.es:10001/api/users/registration/account-confirm-email/{key}/'

    # Realiza la llamada POST al servidor para activar la cuenta
    response = requests.post(api_url, data={'key': key})

    # Comprueba la respuesta y muestra un mensaje adecuado al usuario
    if response.status_code == 200:
        # La cuenta ha sido activada
        return render(request, 'activation_success.html')
    else:
        # Algo salió mal, maneja el error
        return render(request, 'activation_fail.html', {'error': response.text})
"""