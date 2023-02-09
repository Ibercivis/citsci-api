from rest_framework import routers
from django.urls import path
from .views import ProjectsViewSet, TopicsViewSet, HasTagViewSet, ProjectCreateViewSet


router = routers.SimpleRouter()
router.register(r'projects', ProjectsViewSet, basename='projects')
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
router.register(r'project/hastag', HasTagViewSet, basename='project-hastag')

urlpatterns = [
    path('project/create/', ProjectCreateViewSet.as_view(), name='project-create'),
]

urlpatterns += router.urls