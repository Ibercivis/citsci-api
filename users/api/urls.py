from django.urls import path
from django.conf.urls import include
from dj_rest_auth.views import PasswordResetConfirmView

from users.api.views import UserViewSet, UserViewSetDetail

urlpatterns = [
    path('users/registration/', include('dj_rest_auth.registration.urls')),
    path('users/authentication/', include('dj_rest_auth.urls')),
    path('users/authentication/password/reset/confirm/<str:uidb64>/<str:token>', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('users/', UserViewSet.as_view(), name='users'),
    path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),
]