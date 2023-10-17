from django.urls import path
from django.conf.urls import include
#from dj_rest_auth.views import PasswordResetConfirmView

from users.api.views import UserViewSet, UserViewSetDetail, UserProfileView, CountryListView, VisibleUsersListView

urlpatterns = [
    path('users/registration/', include('dj_rest_auth.registration.urls')),
    path('users/authentication/', include('dj_rest_auth.urls')),
    #path('users/authentication/password/reset/', include('dj_rest_auth.password_reset.urls')),
    #path('users/authentication/password/reset/confirm/<str:uidb64>/<str:token>', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('users/', UserViewSet.as_view(), name='users'),
    path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),
    path('users/profile/', UserProfileView.as_view(), name='user-profile'),
    path('users/list/', VisibleUsersListView.as_view(), name='user-list-visible'),
    path('users/countries/', CountryListView.as_view(), name='countries-list'),
]