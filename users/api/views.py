from rest_framework import viewsets
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics, permissions
from django_countries import countries
from django.contrib.auth.models import User
from users.api.serializers import UserSerializer
from users.api.serializers import ProfileSerializer
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import requests
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from dj_rest_auth.registration.views import ConfirmEmailView
import re

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

@method_decorator(csrf_exempt, name='dispatch')
class CustomConfirmEmailView(ConfirmEmailView):
    authentication_classes = []  # Deshabilita todas las clases de autenticación
    permission_classes = [AllowAny]  # Permite el acceso a cualquier usuario, autenticado o no

    @method_decorator(csrf_exempt)
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # Verifica si la confirmación fue exitosa
        if response.status_code == 302:  # 302 es un código de redirección
            return HttpResponse("Confirmación de correo electrónico exitosa.", status=200)
        else:
            return response

@method_decorator(csrf_exempt, name='dispatch')
class ActivateAccountView(View):
    authentication_classes = []  # Deshabilita todas las clases de autenticación
    permission_classes = [AllowAny]  # Permite el acceso a cualquier usuario, autenticado o no

    @method_decorator(csrf_exempt)
    def get(self, request, key):
        # Define la URL de la API para la activación
        api_url = f'{settings.BASE_URL}/api/users/registration/account-confirm-email/{key}/'.format(key=key)

        # Realiza la llamada POST al servidor para activar la cuenta
        response = requests.post(api_url, data={'key': key})

        # Comprueba la respuesta y muestra un mensaje adecuado al usuario
        if response.status_code == 200:
            # La cuenta ha sido activada
            return render(request, 'activation_success.html')
        else:
            # Algo salió mal, maneja el error
            return render(request, 'activation_fail.html', {'error': response.text})

class EmailRecoveryView(View):
    def get(self, request, *args, **kwargs):
        reset_url = request.GET.get('resetUrl', '')
        
        # Extraer uid y token usando una expresión regular
        match = re.search(r'reset/confirm/([^/]+)/([^/]+)$', reset_url)
        if match:
            uid = match.group(1)
            token = match.group(2)
        else:
            uid = ''
            token = ''
        
        print("reset_url: ", reset_url)
        print("UID: ", uid)
        print("Token: ", token)

        context = {
            'uid': uid,
            'token': token,
        }
        return render(request, 'email_recovery.html', context)
    
class RecoverySuccess(View):
    def get(self, request, *args, **kwargs):
        return render(request, 'recovery_success.html')