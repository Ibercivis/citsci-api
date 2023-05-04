from rest_framework import routers
from django.urls import path
from .views import OrganizationViewSet, OrganizationDetailUpdateDelete, OrganizationCreateViewSet, TypeViewSet

urlpatterns = [
    path('organization/create/', OrganizationCreateViewSet.as_view(), name='organization-create'),
    path('organization/<int:pk>/', OrganizationDetailUpdateDelete.as_view(), name='organization-detail-update-delete'),
    path('organization/', OrganizationViewSet.as_view(), name='organization-list'),
    path('organization/type/', TypeViewSet.as_view(), name='organization-type-list'),
]