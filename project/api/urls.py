from rest_framework import routers
from django.urls import path
from .views import ProjectsViewSet, TopicsViewSet, HasTagViewSet, ProjectCreateViewSet, UserViewSet, UserViewSetDetail


router = routers.SimpleRouter()
router.register(r'projects', ProjectsViewSet, basename='projects')
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
router.register(r'project/hastag', HasTagViewSet, basename='project-hastag')

urlpatterns = [
    path('project/create/', ProjectCreateViewSet.as_view(), name='project-create'),
    path('users/', UserViewSet.as_view(), name='users'),
    path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),
]

urlpatterns += router.urls