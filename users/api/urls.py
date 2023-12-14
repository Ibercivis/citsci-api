from django.urls import path
from django.conf.urls import include
#from dj_rest_auth.views import PasswordResetConfirmView
from dj_rest_auth.registration.views import VerifyEmailView, ConfirmEmailView
from django.conf import settings
from django.conf.urls.static import static

from users.api.views import UserViewSet, UserViewSetDetail, UserProfileView, CountryListView, VisibleUsersListView, ActivateAccountView, CustomConfirmEmailView

urlpatterns = [
    path('users/activate-account/<str:key>/', ActivateAccountView.as_view(), name='activate-account'),
    path('users/registration/account-confirm-email/<str:key>/', CustomConfirmEmailView.as_view(), name='account_confirm_email'),
    path('users/registration/', include('dj_rest_auth.registration.urls')),
    path('users/account-confirm-email/', ConfirmEmailView.as_view(), name='account_email_verification_sent'),
    path('users/authentication/', include('dj_rest_auth.urls')),
    #path('users/authentication/password/reset/', include('dj_rest_auth.password_reset.urls')),
    #path('users/authentication/password/reset/confirm/<str:uidb64>/<str:token>', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('users/', UserViewSet.as_view(), name='users'),
    path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),
    path('users/profile/', UserProfileView.as_view(), name='user-profile'),
    path('users/list/', VisibleUsersListView.as_view(), name='user-list-visible'),
    path('users/countries/', CountryListView.as_view(), name='countries-list'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)