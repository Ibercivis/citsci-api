from rest_framework import routers
from django.urls import path
from .views import OrganizationViewSet, OrganizationViewSetDetail, OrganizationViewSetCreateUpdate, TypeViewSet, TypeViewSetDetail, TypeViewSetCreateUpdate

router = routers.SimpleRouter()
router.register(r'organizations', OrganizationViewSet, basename='organizations')
router.register(r'organization/type', TypeViewSet, basename='organization-type')

urlpatterns = [
    path('organization/create/', OrganizationViewSetCreateUpdate.as_view(), name='organization-create'),
]

urlpatterns += router.urls