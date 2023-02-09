from rest_framework import routers
from .views import ProjectsViewSet, TopicsViewSet


router = routers.SimpleRouter()
router.register(r'projects', ProjectsViewSet, basename='projects')
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
urlpatterns = router.urls