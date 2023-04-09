from rest_framework import routers
from django.urls import path
from . import views
from .views import ProjectsViewSet, TopicsViewSet, HasTagViewSet, ProjectCreateViewSet, UserViewSet, UserViewSetDetail


router = routers.SimpleRouter()
# router.register(r'projects', ProjectsViewSet, basename='projects')
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
router.register(r'project/hastag', HasTagViewSet, basename='project-hastag')

urlpatterns = [
    path('project/create/', ProjectCreateViewSet.as_view(), name='project-create'),
    path('users/', UserViewSet.as_view(), name='users'),
    path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),

    # Rutas añadidas por Jorge, pendiente de revisar las anteriores y eliminarlas si no se usan 
    # TODO: llevas la Gestión de usuarios a una aplicación aparte
    path('projects/', views.ProjectListCreate.as_view(), name='project_list_create'),
    path('projects/<int:pk>/', views.ProjectRetrieveUpdateDestroy.as_view(), name='project_retrieve_update_destroy'),
]

urlpatterns += router.urls