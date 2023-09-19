from rest_framework import routers
from django.urls import path
from .views import OrganizationViewSet, OrganizationDetailUpdateDelete, OrganizationCreateViewSet, TypeViewSet
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('organization/create/', OrganizationCreateViewSet.as_view(), name='organization-create'),
    path('organization/<int:pk>/', OrganizationDetailUpdateDelete.as_view(), name='organization-detail-update-delete'),
    path('organization/', OrganizationViewSet.as_view(), name='organization-list'),
    path('organization/type/', TypeViewSet.as_view(), name='organization-type-list'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)