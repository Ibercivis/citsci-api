from rest_framework import routers
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from .views import ProjectsViewSet, TopicsViewSet, HasTagViewSet, ProjectCreateViewSet


router = routers.SimpleRouter()
# router.register(r'projects', ProjectsViewSet, basename='projects')
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
router.register(r'project/hastag', HasTagViewSet, basename='project-hastag')

urlpatterns = [
    path('project/create/', ProjectCreateViewSet.as_view(), name='project-create'),
    # JORGE: Me he llevado estas rutas a la aplicación de usuarios
    # path('users/', UserViewSet.as_view(), name='users'),
    # path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),

    # Rutas añadidas por Jorge, pendiente de revisar las anteriores y eliminarlas si no se usan 
    
    path('project/', views.ProjectListCreate.as_view(), name='project_list_create'),
    path('project/<int:pk>/', views.ProjectRetrieveUpdateDestroy.as_view(), name='project_retrieve_update_destroy'),
    path('projects/<int:project_id>/toggle-like/', views.toggle_project_like, name='toggle_project_like'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += router.urls