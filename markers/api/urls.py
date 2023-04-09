from django.urls import path
from rest_framework.routers import DefaultRouter
from markers.views import MarkerViewSet, AnswerViewSet, ProjectMarkersView
from . import views

router = DefaultRouter()
router.register(r'markers', MarkerViewSet)
router.register(r'answers', AnswerViewSet)

urlpatterns = [
    path('markers/', views.MarkerListCreate.as_view(), name='marker_list_create'),
    path('markers/<int:pk>/', views.MarkerRetrieveUpdateDestroy.as_view(), name='marker_retrieve_update_destroy'),
    path('answers/', views.AnswerListCreate.as_view(), name='answer_list_create'),
    path('answers/<int:pk>/', views.AnswerRetrieveUpdateDestroy.as_view(), name='answer_retrieve_update_destroy'),
    path('projects/<int:project_id>/markers/', ProjectMarkersView.as_view(), name='project-markers'),
] + router.urls